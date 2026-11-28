"""The gate: nothing commits to the ledger without a check (rethink plan §3.2).

For one scene's prose, `gate_scene` runs:

1. **Extract** the scene's commitments with phase 4's rubric
   (`extract.build_commitments_prompt`), offered the facts in force entering
   it and the registry facts recorded for it (`extract.known_for_scene`),
   then ask of each whether it lasts beyond the scene
   (`persistence.judge`): one that doesn't is not proposed (`dropped`,
   reported).
2. **Halt** on decision 2's immediate tier: `audit.halting_conditions` on the
   proposed rows (a `fixed` fact superseded or changed). The third trigger,
   a fact extraction flagged low-confidence, is not wired: phase 4's schema
   has no confidence yet (adding it re-records E3 and E5). A contradiction
   with the plan is the checker's to find (step 3), not extraction's
   (Ben, 2026-10-30): extraction marks added detail as superseding a
   registry fact, and a registry `resolves` is the author's estimate, so a
   `supersedes` or `ends` it proposes on a registry fact is not applied:
   it goes to the checker as a dispute to rule on (a contradiction, or
   cleared). One it doesn't rule on is advisory (E4's re-record, #784):
   reported and listed in working/gate-advisory.csv, never a stop or sent
   to the fix; the plan's fact stands.
3. **Check** the scene against the book and its brief (`checker.check_scene`):
   contradictions and broken promises, by code. `GATE_READINGS` (2)
   independent readings, their union: each reading misses real errors
   another finds. Measured (E8, E4, 2026-11-01): stricter, not more
   convergent (a re-check after the fix still finds things neither first
   reading did), and no gain yet in E4's errors committed.
   A broken promise is `advisory` (#642): reported, kept in
   working/gate-advisory.csv, never fixed or blocking, since a brief is a
   plan and the prose wins. One of a beat the brief marks `must:`
   (`storyforge.must`, `_is_must`) still blocks, as does one of a registry
   fact the ledger sets up in this scene (`_set_up_here`), and a `must`
   beat's quoted words are checked word for word by code
   (`_verbatim_findings`). The typed knowledge check's findings
   (`continuity.is_advisory`) are advisory the same way: reported and
   recorded, never fixed or blocking.
   With `GATE_CHECK_METHOD` `questions` (#649, `storyforge check
   --questions`), the question layer (`questions.check_questions`) checks
   the scene in the open checker's place: narrow yes/no questions from the
   ledger about who is in the scene, each asked twice, a finding only when
   both say yes and the quote verifies. With `tandem` (#738, the default)
   both check a scene's first run, and the question layer alone the
   re-checks after a fix, the open checker's first-run findings standing
   where the fix left their words alone and asked again where it didn't.
4. **Commit** only when nothing halted, extraction left nothing unresolved
   (`UNRESOLVED`: a quote not in the scene, a `supersedes` or `ends` that
   names nothing it can apply to), and the check found nothing, verified or
   not, other than advisory findings and contradictions already in
   the book before the pass
   (`gate_scene(before=)`: `inherited`, reported as `ALREADY IN THE SCENE`
   and kept in working/gate-reported.csv; the commitments stating them are
   held back): the
   scene's commitments replace its earlier ones (`introduced_by` = the
   command that wrote the prose), each registry fact the prose was found to
   establish gets its blank quote filled (`ledger.fill_quote`), and the
   ledger is saved through `ledger.save`, so the audit log has every fact.
5. **Re-check** (Phase 4, `docs/plans/2026-10-31-phase4-safe-revision-design.md`):
   a fact restated keeps its id; the later scenes depending on what the
   scene dropped or changed are listed `RECHECK`, and `recheck_pending`
   re-gates them in reading order (report and stop, under the cost
   threshold). The caller runs it once the scene is committed.

**Fix** (plan §3.2 step 3) is the caller's: a result that didn't pass names
what to fix. The caller must also report `result.problems`' report-only
kinds (`REPORTED`) and `result.inherited` on a pass (`report_lines` has both): they don't make the ledger wrong, but the
author should know. The design is `docs/plans/2026-10-30-gate-ledger-design.md`.

Fails loud: a step that can't finish raises `GateError`, and nothing is
written. A result that didn't pass writes nothing either; it is not an
exception, because the caller decides between fixing and reporting
(advisor mode).
"""

from __future__ import annotations

import copy
import os
import re
import unicodedata
from collections.abc import Callable, Set
from contextlib import contextmanager
from dataclasses import dataclass, field
from functools import cached_property
from typing import NamedTuple, Protocol

from storyforge import audit, ledger, persistence
from storyforge.blocking import BLOCKING_CODE, BLOCKING_READINGS, BlockingError, check_blocking
from storyforge.blocking import COST_PER_READING as BLOCKING_COST_PER_READING
from storyforge.checker import (GATE_READINGS, CheckError, CheckResult, Dispute, Finding,
                               check_scene)
from storyforge.extract import (CLAIM_DEPARTS, CLAIM_KEPT, ENDS_HERE, ENDS_MOVED, ID_PREFIX,
                                MISQUOTE, NO_QUOTE, SPEECH_CLAIM, UNOFFERED)

#: The commands whose prose the gate commits (`ledger.COMMITMENT_WRITERS`
#: without the extract pass)
GATE_COMMANDS = tuple(w for w in ledger.COMMITMENT_WRITERS if w != ledger.COMMITMENTS_PASS)

#: Whether the gate reads each scene's blocking too (`blocking.check_blocking`,
#: #626): `blocking.BLOCKING_READINGS` more calls per scene, on the checker's model
GATE_BLOCKING = True
#: How the gate checks blocking (#647): `read`, the whole-scene blocking read
#: (`blocking.check_blocking`), the default until the stage sheet matches its
#: recall on the blocking set (#646); or `stage-sheet`
#: (`stage_sheet.check_stage_sheet`: a small model records the stage, code
#: checks it), which `storyforge check --stage-sheet` chooses for its run.
#: Either way the findings are BLK against the scene itself
BLOCKING_METHODS = ('read', 'stage-sheet')
GATE_BLOCKING_METHOD = 'read'
#: Whether the gate runs the continuity checks (#648, plan A2:
#: `continuity.check_continuity`): one structured call on a small model
#: reads the scene's typed state (none on a re-check of unchanged prose,
#: which reads its saved file), and code compares it with the book. Its
#: findings join the check's and block like any continuity error; what it
#: couldn't check goes to `GateResult.state_notes`, reported, never blocking
GATE_CONTINUITY = True
#: How the gate checks a scene against the book (#649): `open`, the open
#: checker (`checker.check_scene`, `GATE_READINGS` readings, their union),
#: the default until the question layer and the typed checks match its
#: recall on the frozen E4 and E8; or `questions` (`questions.check_questions`:
#: narrow yes/no questions from the ledger about who is in the scene, each
#: asked twice on a small model, kept only when both say yes and the quote
#: verifies), which `storyforge check --questions` chooses for its run. The
#: question layer takes the scene's cast from its typed state, so it needs
#: `GATE_CONTINUITY`. What it doesn't do (brief promises, filling the quotes
#: of registry facts the prose establishes) is said in
#: `GateResult.question_notes`. Or `tandem` (#738), the default (Ben,
#: 2026-11-26): both checkers on a scene's first gate run, the question
#: layer alone after it (see `OPEN` below). A pilot comparing both modes'
#: catches and false stops on about six scenes may switch it back to
#: `open` (the question layer stopped about 0.48 of gate-set-questions'
#: controls, and a false stop sends a scene into the fix loop, #740); `storyforge check --open` / `--questions` and
#: `write --open` / `--questions` force one for a run
#: (`forced_check_method`)
CHECK_METHODS = ('open', 'questions', 'tandem')
GATE_CHECK_METHOD = 'tandem'
#: #738, the `tandem` method. A gate run that is handed no earlier open
#: reading (`gate_scene(open_from=)`) is a *first run*: the open checker
#: (`GATE_READINGS` readings) and the question layer both check it, and
#: their findings are the union, each tagged with its checker
#: (`Finding.checker`: `OPEN`, `QUESTIONS`, or `BOTH` when both made it).
#: Every gate run of prose the process hasn't open-read is one: a draft's
#: or a redraft's first run, and a re-check or `check --pending` of
#: unchanged prose (the book around it may have changed, which is what the
#: open checker reads). A run that is handed one (`open_from`: the re-check
#: after a fix, its partial-fix retry, a re-roll or re-extraction of the
#: same prose) makes no open reading: the question layer checks it, and the
#: open checker's findings on the prose before stand where the fix left
#: their words alone (`UNTOUCHED`) and are asked again in the fixed prose
#: where it didn't (`questions.ask_resolved`: `STILL_THERE`, or resolved and
#: noted; `_carry_open`). How the two rule on one dispute or ending:
#: `_join_rulings`
OPEN, QUESTIONS, BOTH = 'open', 'questions', 'open, questions'
UNTOUCHED, STILL_THERE = 'untouched', 'still there'
#: The flag that forces each method for a `check` or `write` run
CHECK_FLAGS = {'open': '--open', 'questions': '--questions', 'tandem': '--tandem'}
#: The flag the run forced its method with ('' for none), for the commands
#: a message points to (`pending_command`)
_method_flag = ''


@contextmanager
def forced_check_method(method: str):
    """Run the block with `GATE_CHECK_METHOD` set to `method` (one of
    `CHECK_METHODS`), as `check` and `write` do for a run forced with
    `CHECK_FLAGS[method]`, and put both back after, however it ends (an
    in-process caller after it keeps its own method)."""
    global GATE_CHECK_METHOD, _method_flag
    if method not in CHECK_METHODS:
        raise ValueError(f'{method!r} is not one of {", ".join(CHECK_METHODS)}')
    saved = GATE_CHECK_METHOD, _method_flag
    GATE_CHECK_METHOD, _method_flag = method, CHECK_FLAGS[method]
    try:
        yield
    finally:
        GATE_CHECK_METHOD, _method_flag = saved


#: The flag that forces each extraction thinking setting (`EXTRACT_THINK`)
#: for a `check`, `write` or `revise` run
EXTRACT_THINK_FLAGS = {True: '--extract-thinking', False: '--no-extract-thinking'}
#: The flag of a forced setting that differs from the code's, for the
#: commands a message points to (`pending_command`); '' for none
_think_flag = ''


@contextmanager
def forced_extract_think(think: bool | None):
    """Run the block with `EXTRACT_THINK` set to `think`, as `check`,
    `write` and `revise` do for a run forced with `EXTRACT_THINK_FLAGS`
    (`cli.add_extract_thinking_args`), and put it back after, however it
    ends. None changes nothing. `pending_command` carries the flag when the
    setting differs from the code's."""
    global EXTRACT_THINK, _think_flag
    saved = EXTRACT_THINK, _think_flag
    if think is not None:
        EXTRACT_THINK = bool(think)
        _think_flag = EXTRACT_THINK_FLAGS[EXTRACT_THINK] if EXTRACT_THINK != saved[0] else ''
    try:
        yield
    finally:
        EXTRACT_THINK, _think_flag = saved


def pending_command() -> str:
    """`storyforge check --pending`, with the flag the run forced its check
    method with (#738) and its extraction thinking flag when that differs
    from the code's setting, so the scenes it leaves are checked the same way."""
    return ' '.join(['storyforge check --pending'] + [f for f in (_method_flag, _think_flag) if f])

#: Extraction problems that would commit a wrong row: they block the commit
UNRESOLVED = (MISQUOTE, NO_QUOTE, 'supersedes', 'ends', 'ends again', 'rejected')
#: Extraction problems reported on a pass: a link extraction proposed to a
#: registry fact, not applied (`disagrees`, `ends registry`: the checker
#: judges contradictions with the plan), a subject not in the registries
#: (an object has none), facts left out past the offer cap, facts tied to a
#: scene id that isn't a scene, an `ends` naming a fixed fact (one can't
#: end, so the link is never applied and the row is right without it:
#: G-028, #556, an extraction slip that stopped an unattended run)
#: `ENDS_MOVED` (#621), `ID_PREFIX` (#620), `UNOFFERED` (#634) and
#: `ENDS_HERE` (#734) are links applied, and reported as a NOTE
#: `SPEECH_CLAIM` (#749): a character's spoken account of the past, recorded
#: as their claim and never as a binding fact, is a NOTE: set aside, never
#: silently; so are one code kept binding (`CLAIM_KEPT`) and one telling
#: otherwise than a fact in force (`CLAIM_DEPARTS`)
REPORTED = ('disagrees', 'ends registry', 'subject', 'cap', 'unplaced', 'ends fixed',
            ENDS_MOVED, ID_PREFIX, UNOFFERED, ENDS_HERE, SPEECH_CLAIM, CLAIM_KEPT,
            CLAIM_DEPARTS)
#: #749's review SF-1, SF-5: the kinds every report lists, a passing
#: re-check's too (`applied_lines`), each item, never cut to 20
_CLAIM_KINDS = (SPEECH_CLAIM, CLAIM_KEPT, CLAIM_DEPARTS)
#: What a report line says each `REPORTED` kind means, where its name alone
#: doesn't (#564: `NOTE (cap): scene (62)` said nothing of what was cut)
_REPORTED_LABEL = {
    ENDS_MOVED: 'a state a later scene ended is ended here, its first end in reading '
                'order; the later scene is listed for a re-check',
    ID_PREFIX: 'a link named a fact\'s id without its scene prefix; read as that fact',
    UNOFFERED: 'a link named a fact in force that extraction was not offered (past the '
               'cap); read as that fact, by its id or the nearest id of the same scene',
    ENDS_HERE: 'a state the plan sets up in this scene, with no end given, ends in this '
               'scene too (the check found the scene shows it ending); recorded as a '
               'commitment of the scene that supersedes it, never on the plan\'s row',
    'cap': 'facts in force left out of what extraction was offered, over the cap '
           '(extract.MAX_KNOWN_COMMITMENTS); the scene\'s people and place kept first',
    CLAIM_KEPT: 'extraction marked a character\'s claim in speech that code keeps binding, '
                'a fact the checks hold later scenes to (#749)',
    CLAIM_DEPARTS: 'a claim in speech tells otherwise than a fact in force: recorded as said, '
                   'the fact stands, and the checks read the scene against it (#749)',
    SPEECH_CLAIM: 'a character\'s account in speech of something before the scene and not shown '
           'in it: recorded as their claim (status claim), not as a fact of the world, so no '
           'check holds a scene to it and it changes no fact; conflicting accounts in speech '
           'are kept (#749)',
}
#: Scenes this process's gate runs offered only part of the facts in force,
#: with how many were left out (`prompts.ledger_window_summary`)
OFFER_LEFT_OUT: dict[str, int] = {}


class GateError(RuntimeError):
    """A gate step couldn't finish; nothing was written. From `gate_and_fix`,
    `.first` is the first gate run when there was one, and `.log_dir` the
    invocation's logs (`run_log_dir`)."""
    first: 'GateResult | None' = None
    log_dir: str = ''


class LedgerWriteRefused(GateError):
    """The commit's ledger write was refused (`ledger.save`: rows the next
    command couldn't read, or a cell that would break its row); nothing was
    written and the gate result is as it was before the commit (#599)."""


def _among(f: Finding, findings: list[Finding]) -> bool:
    """Whether `f` is one of `findings`, by identity: `Finding` compares
    by value, and the classified lists hold the check's own objects."""
    return any(f is g for g in findings)


@dataclass
class GateResult:
    scene_id: str
    #: the scene's commitments, as they would be (or were) committed
    proposed: list[dict[str, str]] = field(default_factory=list)
    #: #749: the scene's claims in speech (`extract.SPEECH_CLAIM`, status
    #: `ledger.CLAIM`), committed beside `proposed` as what a character
    #: said, never binding; each is listed in `problems[SPEECH_CLAIM]`
    claims: list[dict[str, str]] = field(default_factory=list)
    #: #749's review CR-2: (statement, why) for each claim in speech the
    #: source tells otherwise: never blocking (conflicting accounts in
    #: speech are kept), reported and listed in `SOURCE_NOTES_PATH`
    claim_departs: list[tuple[str, str]] = field(default_factory=list)
    #: #749's review CR-1: the earlier binding facts of unchanged paragraphs
    #: a claim reads again: no longer kept, so each counts as changed
    unkept_as_claims: list[tuple[str, str]] = field(default_factory=list)
    halts: list[audit.Halt] = field(default_factory=list)
    #: extraction's problems (`extract.COMMITMENT_PROBLEMS` → strings):
    #: `UNRESOLVED` block the commit; `disagrees` and `ends registry` go to
    #: the checker as disputes; the rest of `REPORTED` are for the caller
    problems: dict[str, list[str]] = field(default_factory=dict)
    check: CheckResult | None = None
    committed: bool = False
    #: registry ids whose quote was filled on commit
    quotes_filled: list[str] = field(default_factory=list)
    #: a re-reading of the same prose after the extractor's quote slip
    #: (`gate_scene(hold_slips=True)`): each fact it misquoted (or gave no
    #: quote) again, `fact-id: what` (`_describe_slips`), held back: not
    #: proposed, so never committed, and not a stop (`_hold_slips`)
    slips_held: list[str] = field(default_factory=list)
    #: (statement, why) for each extracted fact the persistence check judged
    #: not to last beyond the scene: not proposed, so never committed
    dropped: list[tuple[str, str]] = field(default_factory=list)
    #: the ends extraction read (`extract.Ending`; #734's review CR-5),
    #: applied on commit (`_apply_ends`), never during the run: an offered
    #: state's end sets its `resolves`; an `ENDS_HERE` claim is a dispute
    #: the check rules on, recorded only when it confirms it
    ends: list = field(default_factory=list)
    #: `ENDS_HERE` claims not recorded on commit, `state id: why`, reported
    ends_held: list[str] = field(default_factory=list)
    #: on commit (Phase 4): the scene's earlier commitments this version
    #: dropped or changed, and the earlier states whose end in this scene
    #: came or went
    changed: list[str] = field(default_factory=list)
    #: on commit: the later scenes, with prose, listed pending for a re-check
    #: because their facts depend on `changed` (`recheck_pending` runs it)
    recheck: list[str] = field(default_factory=list)
    #: on commit (#632): each scene in `recheck` → why it was listed (the
    #: changed fact and the rule, `ledger.Dependents.why`), for the log and
    #: its pending reason
    recheck_why: dict[str, str] = field(default_factory=dict)
    #: on commit: changed fact id → why its dependents can't all be found
    #: (`ledger.Dependents.unrelated`), for the caller to report
    unrelated: dict[str, str] = field(default_factory=dict)
    #: on commit: later scenes depending on `changed` that can't be re-checked
    #: (`scene (why)`: no prose yet, cut or merged), for the caller to report
    not_rechecked: list[str] = field(default_factory=list)
    #: on commit: what narrowed the dependents' name match
    #: (`ledger.subject_names`' notes: a missing registry, no id column),
    #: for the caller to report
    name_notes: list[str] = field(default_factory=list)
    #: on commit (#558): why the earlier prose couldn't be diffed (so every
    #: reworded fact counts as changed), or why this prose wasn't recorded
    prose_notes: list[str] = field(default_factory=list)
    #: on commit (#558): the earlier commitments kept as they were, read from
    #: paragraphs the new prose has unchanged and in place (`steady_facts`)
    steady: list[str] = field(default_factory=list)
    #: on commit (#599): proposed rows dropped as a reading again of a kept
    #: (`steady`) fact, `(statement, kept id)`: reported, never silent
    reread: list[tuple[str, str]] = field(default_factory=list)
    #: on commit (#599): proposed rows committed as new facts that read much
    #: like a kept fact of the same subject and type (`_RESTATES`), `(statement,
    #: kept id)`, for the author to judge: a second fact or a copy
    restates: list[tuple[str, str]] = field(default_factory=list)
    #: on commit: registry rows (the author's) whose `supersedes`/`depends_on`
    #: names a commitment this version removed (`row → id`): a re-check
    #: replaces only commitments, so the author must fix the link
    dangling: list[str] = field(default_factory=list)
    #: verified contradictions that were in the book before the pass that
    #: wrote this prose (`_classify`): the author's to fix, reported (and
    #: kept in working/gate-reported.csv on commit) but not blocking, and
    #: never sent to the fix. A subset of `check.findings`, set once
    inherited: list[Finding] = field(default_factory=list)
    #: verified contradictions in the brief's own scripted words
    #: (`_brief_lines`, `_is_plan_conflict`): the brief and the book
    #: disagree, so no prose edit can deliver one without breaking the
    #: other. They block, and go to the author rather than the fix. A subset
    #: of `findings`, disjoint from `inherited`
    plan_conflicts: list[Finding] = field(default_factory=list)
    #: (plan conflict, whether its speaker was checked and why not), for
    #: the report (`_plan_conflict`)
    speaker_notes: list[tuple[Finding, str]] = field(default_factory=list)
    #: findings that don't stop the scene: every broken promise (#642),
    #: verified or not, except one of a beat the brief marks `must:`
    #: (`_is_must`) or of a registry fact the ledger sets up in this scene
    #: (`_set_up_here`), since a brief is a plan and the prose wins; and
    #: every finding of an advisory continuity check
    #: (`continuity.is_advisory`: the typed knowledge check, whose
    #: learning points are read from briefs and a model's records).
    #: Reported (`ADVISORY`), kept in `ADVISORY_PATH`, never sent to the
    #: fix. Set by `_classify`; disjoint from `findings` and `unverified`
    advisory: list[Finding] = field(default_factory=list)
    #: (broken promise, why it blocks) for each one that isn't advisory: a
    #: `must` beat (`MUST_BEAT`) or a registry fact set up in this scene
    #: (`SET_UP_HERE`); set by `_classify`, for the report
    promise_why: list[tuple[Finding, str]] = field(default_factory=list)
    #: brief items that are only the `must:` marker (`field (n)`): they
    #: mark nothing, and are reported
    bare_must: list[str] = field(default_factory=list)
    #: scripted words of `must` items too short to find by code
    #: (`field: "words"`, `_verbatim_findings`): left to the check, reported
    short_must: list[str] = field(default_factory=list)
    #: brief items whose `must:` marks nothing (`field: item`): written
    #: after other words, or in a field that takes no marker; reported
    misplaced_must: list[str] = field(default_factory=list)
    #: on commit: (statement, inherited finding) for each extracted
    #: commitment stating an inherited contradiction, not recorded
    #: (`_hold_back`)
    held_back: list[tuple[str, Finding]] = field(default_factory=list)
    #: on a provisional commit (#735): (statement, finding) for each
    #: extracted commitment stating a finding the scene was committed in
    #: spite of (`_hold_back`'s `also`): recorded as disputed, status
    #: `pending` (not in force) with `reviewed` `HELD` + its finding's key
    #: (`is_held`), until `accept_blocked` accepts the finding or a re-gate
    #: of the scene replaces it. Their rows are in `disputed_rows`
    disputed: list[tuple[str, Finding]] = field(default_factory=list)
    disputed_rows: list[dict[str, str]] = field(default_factory=list)
    #: on commit (#632): (statement, finding) for each kept (`steady`) fact
    #: the hold-back would have taken: it stays as it was, since its prose
    #: didn't change, and is reported
    kept_stating: list[tuple[str, Finding]] = field(default_factory=list)
    #: (finding, why) for each verified contradiction with an earlier scene
    #: the source backs this scene on (`gate_source`, #557): not blocking,
    #: never sent to the fix; the earlier scene is listed `SOURCE_FIX` on
    #: commit. Disjoint from `inherited` and `plan_conflicts`
    source_backed: list[tuple[Finding, str]] = field(default_factory=list)
    #: (statement, why) for each extracted fact the source contradicts
    #: (#557, B-027): still committed (#742: the ledger records what the
    #: book says, and the source's text has its own slips), reported, and
    #: the scene listed for the author (`SOURCE_FIX_PATH`) on commit
    source_departs: list[tuple[str, str]] = field(default_factory=list)
    #: (finding, source quote, why) for each blocking finding the source
    #: narrates the same way (#742): it still blocks (Ben, 2026-11-26: a
    #: slip inside a scene is smoothed even when the original has it), and
    #: is listed for the author (`SOURCE_NOTES_PATH`)
    source_has_it: list[tuple[Finding, str, str]] = field(default_factory=list)
    #: why the source check didn't run, or what it didn't rule on
    source_notes: list[str] = field(default_factory=list)
    #: on commit: the earlier scenes' commitments marked `superseded`
    #: because the source backs this scene against them (#557's review)
    source_superseded: list[str] = field(default_factory=list)
    #: on commit: source-backed findings whose earlier fact wasn't found
    #: (its commitments are held back instead)
    source_unmatched: list[Finding] = field(default_factory=list)
    #: the source check ruled on every fact new to the scene (#557's third
    #: review: only then can a fix toward the source retire anything)
    source_ruled: bool = False
    #: committed without a pass (`commit_provisional`, `write --keep-going`)
    provisional: bool = False
    #: #631/#647: how the prose's blocking was checked (one of
    #: `BLOCKING_METHODS`; '' when it wasn't): this run checked it, or skipped
    #: it as already checked the same way on the same prose; recorded with
    #: the prose on commit (`record_prose`)
    blocking_method: str = ''
    #: #631: this re-check skipped the blocking read (the prose is the gated
    #: prose, which had one); the scene's reported blocking findings are kept
    blocking_skipped: bool = False
    #: #631: on a re-check, whether the blocking read ran and why, for the log
    #: and the report
    blocking_note: str = ''
    #: #647: what the stage sheet couldn't check (`StageResult.notes`), for
    #: the log and the report; never blocking
    stage_notes: list[str] = field(default_factory=list)
    #: #648: what the continuity checks couldn't check, and advisory names
    #: (`ContinuityResult.notes`), for the log and the report; never blocking
    state_notes: list[str] = field(default_factory=list)
    #: #649: with `GATE_CHECK_METHOD` `questions`, what the question layer
    #: couldn't ask or answer, and what it doesn't check, for the log and the
    #: report; never blocking
    question_notes: list[str] = field(default_factory=list)
    #: #677: the ledger fact ids the question layer asked about
    #: (`QuestionResult.asked_fact_ids`), in order, each once
    asked_fact_ids: list[str] = field(default_factory=list)
    #: #738: under `tandem`, which checkers read this run, what became of
    #: the first run's open findings on a re-check, and where the two
    #: checkers ruled a dispute or an ending differently; for the log and
    #: the report, never blocking
    check_notes: list[str] = field(default_factory=list)
    #: #738: under `tandem`, the open checker's findings standing in this
    #: run (its own reading's, or those carried from the run before), on
    #: `open_prose`, for a later run of the same process to carry
    #: (`_carry_open`); None when no open reading is behind this run
    open_findings: 'list[Finding] | None' = field(default=None, repr=False, compare=False)
    open_prose: str = field(default='', repr=False, compare=False)
    #: #738: under `tandem`, the open checker's rulings on disputes and
    #: endings standing in this run (`OpenRulings`: its own reading's, or
    #: those carried), for a re-check to carry (`_carry_rulings`)
    open_rulings: 'OpenRulings | None' = field(default=None, repr=False, compare=False)
    #: #736: on the re-check after a fix, whether extraction was carried from
    #: the run before it or read again, and why (`_extract`'s note), for the
    #: log; '' on a run that isn't a fix's re-check
    extract_note: str = ''
    #: #736: what this run's extraction read (or carried), for the re-check
    #: after a fix (`_carry_of`); None when the run didn't reach extraction
    _extracted: 'object' = field(default=None, repr=False, compare=False)
    #: what `_commit` needs from the run (`_CommitContext`); None until the
    #: run reaches the check
    _ctx: 'object' = field(default=None, repr=False, compare=False)

    @property
    def findings(self) -> list[Finding]:
        """The check's verified findings, less `inherited`, `source_backed`
        and `advisory`."""
        if not self.check:
            return []
        backed = [f for f, _ in self.source_backed]
        return [f for f in self.check.findings
                if not _among(f, self.inherited) and not _among(f, backed)
                and not _among(f, self.advisory)]

    @property
    def fixable(self) -> list[Finding]:
        """`findings` less `plan_conflicts`: the verified ones the fix is for."""
        return [f for f in self.findings if not _among(f, self.plan_conflicts)]

    @property
    def unverified(self) -> list[Finding]:
        """Findings whose quotes didn't hold up: not shown to be wrong, so
        they block the commit like any other finding. Less `advisory`: a
        broken promise that wouldn't block verified doesn't block unverified."""
        if not self.check:
            return []
        return [f for f in self.check.unverified if not _among(f, self.advisory)]

    @property
    def unresolved(self) -> list[str]:
        """Extraction problems that block the commit (`UNRESOLVED`)."""
        return [f'{kind}: {item}' for kind in UNRESOLVED
                for item in self.problems.get(kind, [])]

    @property
    def unruled(self) -> list[Dispute]:
        """Registry facts extraction said the scene changes that the checker
        neither ruled a contradiction nor cleared. Advisory (Ben,
        2026-11-27; E4's re-record, #784: `eleven-days` stopped in two runs
        on one alone): reported (`ADVISORY`), listed in `ADVISORY_PATH`
        (`record_advisory`), never a stop or sent to the fix. The link is
        not applied, so the plan's fact stands, as for a cleared one."""
        return self.check.unruled if self.check else []

    @property
    def passed(self) -> bool:
        return not (self.halts or self.unresolved or self.findings or self.unverified)


def _subjects(project_dir: str) -> dict[str, str]:
    from storyforge.enrich import load_registry_alias_maps
    maps = load_registry_alias_maps(project_dir)
    return {**maps.get('locations', {}), **maps.get('characters', {})}


#: #743: whether the gate's extraction call (and E3's, which measures it)
#: lets the model think. On (Ben, 2026-11-26), which sends no thinking
#: setting, the request main sent before #743. Off (`api.thinking_off`) was
#: measured: median 16 s against about 42 s, 37% fewer output tokens, E3
#: 42/7/0 captured/partial/missing against 43/5/1, but 13.5% fewer rows,
#: and the rows lost were mostly a scene's final state changes, which the
#: continuity checks rely on (docs/history.md, #743). Revisit after a real
#: book run. False re-keys every recording of the call (re-record E3 and
#: the gate sets). `check`, `write` and `revise` take `--extract-thinking` /
#: `--no-extract-thinking` to set it for one run (`forced_extract_think`)
EXTRACT_THINK = True
#: The answer budget of the gate's extraction call (`api.THINKING_ALLOWANCE`
#: is added for thinking; with it off, headroom for the answer). It is part of the
#: recorded request, so a change re-keys every recording of the call: the
#: largest answer logged on iliad-adult (2026-11-16/17, 117 calls, thinking
#: on) was 5,796 tokens, with 17,314 output in all of the 24,000 sent
EXTRACT_ANSWER_TOKENS = 8000
#: #734: the budget of the one retry after a reply cut off at
#: `EXTRACT_ANSWER_TOKENS` (the model's own limit caps it): a cut-off raised
#: `GateError` and stopped the session, on the densest scenes. Only a
#: cut-off sends it, so recordings of whole replies replay as they were.
#: With `EXTRACT_THINK` off (#743) the first request's whole budget is
#: answer, so a cut-off is rarer, and this one still adds 16,000 tokens
EXTRACT_RETRY_TOKENS = 24000


@dataclass
class _Extracted:
    """#736: what a gate run's extraction read, kept on its `GateResult` so
    the re-check after a fix can reuse it (`_carry_reason`): the model's
    replies, never the rows made from them, which are made again by code
    from the fixed prose."""
    #: the prose the model read (a carried run keeps its source's)
    prose: str
    #: the extraction prompt with the scene left out (`build_commitments_prompt`
    #: with no prose): everything else the model was shown
    context: str
    model: str
    #: the parsed extraction reply (`parse_commitments_response`)
    found: list[dict]
    #: the persistence check's verdict on `found`
    kept: list[dict]
    dropped: list[tuple[dict, str]]
    #: #736's review CR-1: set by `_carry_of`: the continuity checks' state
    #: codes among the findings sent to the fix
    state_codes: frozenset = frozenset()
    #: `EXTRACT_THINK` when it was read: a request with another setting is
    #: another request, so it isn't carried (`_carry_reason`)
    think: bool = True


def _word_offsets(text: str) -> tuple[str, list[tuple[int, int]]]:
    """`text` normalized and lowercased as `_word_list` reads it, and each of
    its words' character span there."""
    from storyforge.checker import normalize
    flat = normalize(text).lower()
    return flat, [m.span() for m in re.finditer(r'\w+', flat)]


def _window(flat: str, offsets: list[tuple[int, int]], span: 'Span') -> str:
    """The characters of `flat` from the end of the word `_NEAR_WORDS` before
    `span` to the start of the word `_NEAR_WORDS` after it: the quote, its
    punctuation and the words beside it."""
    start = offsets[span.start - _NEAR_WORDS][1] if span.start >= _NEAR_WORDS else 0
    after = span.end + _NEAR_WORDS - 1
    end = offsets[after][0] if after < len(offsets) else len(flat)
    return flat[start:end]


def _quote_untouched(quote: str, diff: '_Diff', before: tuple | None = None,
                     after: tuple | None = None) -> bool:
    """#736: whether `quote` is in the fixed prose (`diff.after`) and no
    place it is found comes near a change (`_touches(near=True)`): words
    put in or taken out beside a quote can change what it says. With
    `before` and `after` (`_word_offsets` of each prose; #736's review
    SF-3), the characters around each place, its punctuation included,
    must also be in the prose before: "dead." made "dead?" is a change the
    word diff can't see."""
    return _untouched(_quote_spans(quote, diff.after), diff.after_spans, after, before)


def _untouched(places: list['Span'], changed: list['Span'], own: tuple | None = None,
               other: tuple | None = None) -> bool:
    """The one test of "away from the fix" (#736's carry and #737's
    never-worse rule): there are `places`, none comes near a `changed`
    span (`_touches(near=True)`), and with `own` and `other` (`_word_offsets`
    of the prose the places are in, and of the prose on the diff's other
    side) the characters around each place, its punctuation included
    (`_window`), are in the other prose too."""
    if not places or any(_touches(p, changed, near=True) for p in places):
        return False
    if own is None or other is None:
        return True
    return all(_window(own[0], own[1], p) in other[0] for p in places)


def _quoted_list(what: str, quotes: list[str]) -> str:
    first = _one_line(quotes[0])
    return (f'{what} of {len(quotes)} fact(s) ("{first[:60]}{"…" if len(first) > 60 else ""}"'
            + (f' and {len(quotes) - 1} more' if len(quotes) > 1 else '') + ')')


def _carry_reason(carry: _Extracted, prose: str, context: str, model: str) -> str:
    """#736: why `carry` (the extraction of the prose before a fix) can't
    stand for an extraction of `prose`; '' when it can: the same model,
    shown the same facts in force, registries and scene details; every
    fact it read (those persistence dropped too) quoted from words of
    `prose` the fix left alone, away from every change, its punctuation
    and the characters beside it unchanged (`_quote_untouched`); and, when
    the fix put words in anywhere, no fact it read a state (#736's review
    CR-1: words far from a state's quote can end or replace it, "Mara
    handed Tom the key" leaving "Mara holds the key" in force) and no
    finding sent to the fix one of the continuity checks' state codes
    (`carry.state_codes`: a fix for a state writes a change of state). Then
    the rows are made again from its replies by code, against `prose`."""
    if carry.model != model:
        return 'the extraction model differs'
    if carry.think != EXTRACT_THINK:
        return 'the extraction thinking setting differs'
    if carry.context != context:
        return ('the facts in force, the registries or the scene\'s details changed since it '
                'was read')
    quotes = [e.get('quote') or '' for e in carry.found]
    if any(not q.strip() for q in quotes):
        return f'{sum(not q.strip() for q in quotes)} fact(s) read have no quote to check'
    diff = _diff(carry.prose, prose)
    never = [q for q in quotes if not _quote_spans(q, diff.before)]
    if never:
        return _quoted_list('the prose read never had the quote', never)
    before, after = _word_offsets(carry.prose), _word_offsets(prose)
    touched = [q for q in quotes if not _quote_untouched(q, diff, before, after)]
    if touched:
        return _quoted_list('the fix changed words or punctuation in or beside the quote',
                            touched)
    if any(b > a for a, b in diff.after_spans):
        states = [q for e, q in zip(carry.found, quotes) if e.get('mutable') == 'state']
        if states:
            return _quoted_list('the fix put words in, which can end or change a state: '
                                'the state', states)
        if carry.state_codes:
            return (f'the fix put words in for a state finding '
                    f'({", ".join(sorted(carry.state_codes))}), which can change a state')
    return ''


def _extract(project_dir: str, scene_id: str, prose: str, rows: list[dict[str, str]],
             order: dict[str, int], introduced_by: str, model: str, log_dir: str,
             problems: dict[str, list[str]],
             dropped: list[tuple[str, str]], *,
             reserved: Set[str], ends: list | None = None,
             carry: _Extracted | None = None, refused: str = '',
             read_out: list | None = None,
             pinned: dict | None = None) -> list[dict[str, str]]:
    """The scene's commitments read from `prose` against `rows`, each with an
    id no row of `rows` and none of `reserved` has (#599; required, #599's
    review TD-2: `_reserved_ids`). The ends read go to `ends`
    (`extract.Ending`), none applied to `rows`; an `ENDS_HERE` claim on a
    state a later scene leans on is `ends registry` instead
    (`_route_leaned_on`).

    #736: with `carry` (the extraction of the prose before a fix), its
    replies stand for this prose when `_carry_reason` finds nothing against
    them: no extraction or persistence call; the rows, problems and ends are
    made from them again by code, against `prose`. Otherwise the scene is
    extracted as without it (the same requests). `refused` is why the run
    before had nothing to carry (`_carry_of`). `read_out` gets
    `(_Extracted, note)`: what this run read or carried, and the log line
    saying which and why ('' when nothing was offered or refused).
    `pinned` (#788, `gate_scene`): an eval's frozen replies, used as they
    are, with no call."""
    from storyforge.extract import build_commitments_prompt, commitment_rows, unplaced_rows
    known, recorded, left_out, details, registries_text = _extraction_inputs(
        project_dir, scene_id, rows, order)
    subjects = _subjects(project_dir)
    OFFER_LEFT_OUT.pop(scene_id, None)   # this run's count, not an earlier gate run's
    if left_out:
        problems['cap'].append(f'{scene_id} ({left_out})')
        OFFER_LEFT_OUT[scene_id] = left_out
    problems['unplaced'].extend(unplaced_rows(rows, order))
    context = build_commitments_prompt(scene_id, '', details, registries_text=registries_text,
                                       known=known, recorded=recorded)
    why_not = _carry_reason(carry, prose, context, model) if carry is not None else ''
    if pinned is not None:
        found = copy.deepcopy(pinned['found'])
        verdict = persistence.Verdict(kept=copy.deepcopy(pinned['kept']),
                                      dropped=[(copy.deepcopy(e), why)
                                               for e, why in pinned['dropped']])
        note = f'extraction pinned by the eval ({len(found)} fact(s) read): no extraction call'
        source = prose
    elif carry is not None and not why_not:
        found = copy.deepcopy(carry.found)
        verdict = persistence.Verdict(kept=copy.deepcopy(carry.kept),
                                      dropped=copy.deepcopy(carry.dropped))
        note = (f'extraction carried from the prose before the fix: no fact\'s quote was '
                f'changed ({len(found)} fact(s) read); words the fix put in are not read for '
                f'new facts')
        source = carry.prose
    else:
        found, verdict = _read_commitments(
            scene_id, prose, build_commitments_prompt(scene_id, prose, details,
                                                      registries_text=registries_text,
                                                      known=known, recorded=recorded),
            model, log_dir)
        why_not = why_not or refused
        note = f'extracted again: {why_not}' if why_not else ''
        source = prose
    if read_out is not None:
        read_out.append((_Extracted(source, context, model, copy.deepcopy(found),
                                    copy.deepcopy(verdict.kept),
                                    copy.deepcopy(verdict.dropped),
                                    think=EXTRACT_THINK), note))
    dropped.extend((e['statement'], why) for e, why in verdict.dropped)
    ends = [] if ends is None else ends
    from storyforge.extract import Speakers
    out = commitment_rows(verdict.kept, scene_id, prose, rows, known, recorded, subjects,
                          introduced_by, problems, own_writers=ledger.COMMITMENT_WRITERS,
                          registry_is_plan=True, reserved=reserved, order=order,
                          ends_out=ends, speakers=Speakers.load(project_dir))
    _route_leaned_on(project_dir, scene_id, rows, order, ends, problems)
    return out


def _extraction_inputs(project_dir: str, scene_id: str, rows: list[dict[str, str]],
                       order: dict[str, int]) -> tuple[list, list, int, dict, str]:
    """What the gate's extraction prompt is built from, besides the prose:
    the facts in force offered (`known`), the registry facts recorded for
    the scene (`recorded`), how many were left out of the offer, the
    scene's details and the registries' text."""
    from storyforge.elaborate import get_scene
    from storyforge.enrich import format_registries_for_prompt
    from storyforge.extract import known_for_scene
    scene = get_scene(scene_id, os.path.join(project_dir, 'reference')) or {}
    subjects = _subjects(project_dir)
    names = ([scene.get('pov', '')] + scene.get('location', '').split(';')
             + scene.get('on_stage', '').split(';'))
    scene_subjects = {subjects[n.strip().lower()] for n in names if n.strip().lower() in subjects}
    known, recorded, left_out = known_for_scene(rows, scene_id, order, scene_subjects)
    details = {k: scene.get(k, '') for k in ('title', 'pov', 'location')}
    return (known, recorded, left_out, details,
            format_registries_for_prompt(project_dir, exclude=('knowledge',)))


def extraction_prompt(project_dir: str, scene_id: str, prose: str,
                      rows: list[dict[str, str]] | None = None) -> str:
    """#788: the prompt the gate's extraction sends for `prose` as
    `scene_id`, read against `rows` (the ledger, read when None, less the
    scene's own commitments, as a redraft is read). For an eval that
    measures extraction on a real book."""
    if rows is None:
        rows = [r for r in ledger.load(project_dir)
                if not (r.get('scene_id') == scene_id and ledger.is_commitment(r))]
    from storyforge.extract import build_commitments_prompt
    known, recorded, _, details, registries_text = _extraction_inputs(
        project_dir, scene_id, rows, ledger.scene_order(project_dir))
    return build_commitments_prompt(scene_id, prose, details, registries_text=registries_text,
                                    known=known, recorded=recorded)


def pinned_extraction(result: 'GateResult') -> dict | None:
    """#788: what `result`'s extraction read, as JSON-ready data for an eval
    to pin (`gate_scene(pinned=)`): the extraction reply (`found`) and the
    persistence check's verdict (`kept`, `dropped` as [entry, why] pairs).
    None when the run didn't reach extraction."""
    read = result._extracted
    if read is None:
        return None
    return {'found': copy.deepcopy(read.found), 'kept': copy.deepcopy(read.kept),
            'dropped': [[copy.deepcopy(e), why] for e, why in read.dropped]}


def _read_commitments(scene_id: str, prose: str, prompt: str, model: str,
                      log_dir: str) -> tuple[list[dict], 'persistence.Verdict']:
    """The extraction call on `prompt` (asked again once, with a larger
    budget, when its reply is cut off; #734) and the persistence check on
    what it read."""
    from storyforge.api import extract_text, invoke_to_file, is_truncated
    from storyforge.extract import COMMITMENTS_SCHEMA, parse_commitments_response
    log_file = os.path.join(log_dir, f'gate-extract-{scene_id}.json')
    try:
        response = invoke_to_file(prompt, model, log_file, EXTRACT_ANSWER_TOKENS,
                                  output_schema=COMMITMENTS_SCHEMA, label=f'extract {scene_id}',
                                  think=EXTRACT_THINK)
        if is_truncated(response):
            from storyforge.common import log
            log(f'  {scene_id}: the extraction reply was cut off at its token limit; asking '
                f'again with a larger one')
            response = invoke_to_file(prompt, model,
                                      os.path.join(log_dir, f'gate-extract-{scene_id}.retry.json'),
                                      EXTRACT_RETRY_TOKENS, output_schema=COMMITMENTS_SCHEMA,
                                      label=f'extract {scene_id} (retry)', think=EXTRACT_THINK)
        if is_truncated(response):
            raise ValueError('the reply hit its token limit, twice')
        found = parse_commitments_response(extract_text(response), scene_id)
    except (RuntimeError, ValueError) as e:   # RefusalError, an API failure, a bad reply
        raise GateError(f'{scene_id}: extraction failed: {e}') from e
    try:
        verdict = persistence.judge(scene_id, prose, found, model=model,
                                    log_file=os.path.join(log_dir,
                                                          f'gate-persistence-{scene_id}.json'))
    except persistence.PersistenceError as e:
        raise GateError(str(e)) from e
    return found, verdict


def _route_leaned_on(project_dir: str, scene_id: str, rows: list[dict[str, str]],
                     order: dict[str, int], ends: list,
                     problems: dict[str, list[str]]) -> None:
    """#734's review CR-1: an `ENDS_HERE` claim on a state a later scene
    leans on (its brief names it, `audit.leaning_scenes`, or a later binding
    row supersedes it or names it in `depends_on`) is taken off `ends` and
    reported `ends registry` for the checker: ending it here would
    contradict the plan. One that can't be checked (scene-briefs.csv
    unreadable) is routed the same way, and says why."""
    from storyforge.extract import ENDS_HERE
    here = [e for e in ends if e.kind == ENDS_HERE]
    if not here:
        return
    at = order[scene_id]
    try:
        leaning = audit.leaning_scenes(project_dir, [e.state_id for e in here])
        why_not = ''
    except (OSError, UnicodeDecodeError, ValueError) as err:
        leaning, why_not = {}, f'scene-briefs.csv not read: {err}'
    for e in here:
        later = [s for s in leaning.get(e.state_id, []) if order.get(s, -1) > at]
        later += [r['id'] for r in rows if r.get('status') == 'binding'
                  and order.get((r.get('scene_id') or '').strip(), -1) > at
                  and e.state_id in (ledger._split(r.get('supersedes', ''))
                                     + ledger._split(r.get('depends_on', '')))]
        if not later and not why_not:
            continue
        ends.remove(e)
        because = (f'later scenes lean on it: {", ".join(later)}' if later else why_not)
        problems['ends registry'].append(
            f'{scene_id}: {e.state_id} (resolves: blank; {_one_line(because)})')


def _disputes(result: GateResult, rows: list[dict[str, str]]) -> list[Dispute]:
    """Each registry fact extraction says the scene changes, for the
    checker to rule on (Ben, 2026-10-30: the checker decides). From
    `commitment_rows`' problem strings: `disagrees` is `scene: registry-id
    (prose: proposed-id)`, `ends registry` is `scene: registry-id
    (resolves: ...)`."""
    import re
    # #749's review SF-3: a claim naming a registry fact is a dispute too
    proposed = {r['id']: r for r in result.proposed + result.claims}
    out: dict[str, Dispute] = {}
    for item in result.problems.get('disagrees', []):
        m = re.match(r'[^:]+: (\S+) \(prose: (\S+)\)$', item)
        if not m:
            continue
        row = proposed.get(m.group(2), {})
        out.setdefault(m.group(1), Dispute(m.group(1), _statement(rows, m.group(1)),
                                           row.get('quote') or row.get('statement', '')))
    for item in result.problems.get('ends registry', []):
        m = re.match(r'[^:]+: (\S+) \(resolves: ([^)]*)\)$', item)
        if not m:
            continue
        out.setdefault(m.group(1), Dispute(
            m.group(1), _statement(rows, m.group(1)),
            f'the state ends in this scene (the plan says it ends at {m.group(2)})'))
    return list(out.values())


def _endings(result: GateResult, rows: list[dict[str, str]]) -> list[Dispute]:
    """#734's re-review (SF-1): each `ENDS_HERE` claim, a state the plan
    sets up in this scene that extraction read as ending here, for the check
    to rule on with a question of its own: does the scene show it ending?
    (`check_scene(endings=)`, `questions.ending_question`). Not a dispute: a
    dispute asks whether the scene contradicts the fact, and clearing one
    means it leaves the fact standing."""
    from storyforge.extract import ENDS_HERE
    return [Dispute(e.state_id, _statement(rows, e.state_id),
                    _one_line(e.carrier.get('quote') or e.carrier.get('statement', '')))
            for e in result.ends if e.kind == ENDS_HERE]


def _statement(rows: list[dict[str, str]], rid: str) -> str:
    return next((r.get('statement', '') for r in rows if r.get('id') == rid), '')


def _words(text: str) -> str:
    """`text` as lowercase words, one space apart, padded: a phrase is
    in it when `_words(phrase)` is a substring. NFC first, so a name typed
    with a combining accent (decomposed) matches the same name composed."""
    text = unicodedata.normalize('NFC', text)
    return ' ' + ' '.join(re.findall(r'\w+', text.lower())) + ' '


def _count(words: str) -> int:
    return len(words.split())


#: A quote matched against the scene before the pass needs this many words
#: in all, and each part (split at an ellipsis) `_MIN_PART_WORDS`: a short
#: one ("twelve", "the barn") turns up in old prose by accident (#480's review)
_MIN_QUOTE_WORDS = 4
_MIN_PART_WORDS = 3


def _found_in(quote: str, text: str) -> bool:
    """Whether `quote`'s parts (split at an ellipsis) are in `text`, in
    order, ignoring case, punctuation and spacing; no minimum length."""
    words, at = _words(text), 0
    parts = [p for p in (_words(x) for x in re.split(r'\.\.\.|…', quote)) if p.strip()]
    for p in parts:
        found = words.find(p, at)
        if found < 0:
            return False
        at = found + len(p) - 1
    return bool(parts)


def _quoted_in(quote: str, text: str) -> bool:
    """Whether `quote` is in `text`, ignoring case, punctuation and spacing:
    its parts (split at an ellipsis, as quotes are verified) in order, each
    of `_MIN_PART_WORDS` words or more and `_MIN_QUOTE_WORDS` in all. A
    shorter quote is never found: the safe answer, since a found quote
    makes a finding inherited."""
    parts = [_words(p) for p in re.split(r'\.\.\.|…', quote)]
    parts = [p for p in parts if p.strip()]
    if (not parts or sum(_count(p) for p in parts) < _MIN_QUOTE_WORDS
            or any(_count(p) < _MIN_PART_WORDS for p in parts)):
        return False
    words, at = _words(text), 0
    for p in parts:
        found = words.find(p, at)
        if found < 0:
            return False
        at = found + len(p) - 1   # the next part may start at this one's closing space
    return True


#: The fewest words a brief's own words must have to count as the source of
#: a contradiction: shorter ones ("Yes.") match by accident
_MIN_BRIEF_WORDS = 3


class Scripted(NamedTuple):
    """A phrase the brief scripts (`_brief_lines`), and the character it
    gives the line to, when the brief says (`_label_speaker`)."""
    text: str
    #: the speaker's characters.csv id (its name, for a row with no id);
    #: None: the brief names no one, or not with confidence
    speaker: str | None = None
    #: why `speaker` is None, for the report (`_NO_LABEL` and the rest)
    why: str = 'the brief names no speaker'


#: Why a scripted phrase has no speaker (`Scripted.why`)
_NO_QUOTES = 'the brief line has no quote marks'
_NO_LABEL = 'the brief names no speaker'
_SHARED = 'the brief names a name two characters share'
_UNCLEAR = 'the brief\'s speaker label is not clear'
_NO_CAST = 'no characters in characters.csv'


def _not_in_cast(label: str) -> str:
    """Why a label that starts with no character's name gives no speaker."""
    if len(label) > 40:
        label = label[:40].rstrip() + '…'
    return f'the brief\'s label "{label}" names no one in characters.csv'


#: Words that may come before the name in a label (`_named`)
_LABEL_JOINS = frozenset({'and', 'then'})


@dataclass(frozen=True)
class Cast:
    """The characters a speech tag may name (`_cast`, from
    reference/characters.csv)."""
    #: each name, alias and id, as `_words` without the padding → the ids
    #: of the characters it names (more than one: a shared name)
    ids: dict[str, frozenset[str]] = field(default_factory=dict)
    #: id → subject pronoun (`schema.pronoun_key`), only where it is known
    pronouns: dict[str, str] = field(default_factory=dict)
    #: id → name, for the report
    display: dict[str, str] = field(default_factory=dict)
    #: what about the file, or an adaptation's source, keeps speakers from
    #: being checked (WARNINGs)
    warnings: tuple[str, ...] = ()

    @property
    def names(self) -> frozenset[str]:
        return frozenset(self.ids)

    @cached_property
    def longest(self) -> int:
        """The most words any name, alias or id has (`_name_at`)."""
        return _longest(self.ids)


def _longest(names) -> int:
    """The most words any of `names` (as `_words`, no padding) has; 1 for
    none, so a pronoun is still a tag's speaker."""
    return max((n.count(' ') + 1 for n in names), default=1)


def _cast(project_dir: str) -> Cast:
    """The characters (reference/characters.csv): names, aliases and ids,
    and each one's pronouns when the file has a `pronouns` column and the
    cell is one `schema.pronoun_key` reads, or, for an empty cell in an
    adaptation, the imported source's (`source.character_pronouns`). A
    missing file, or one with no named rows, is no one, and a pronoun cell
    that can't be read is unknown, as is a source that can't be read or
    whose value can't be used: each is a `Cast.warnings` line
    (`_warn_once`), since speakers then go unchecked."""
    from storyforge import source
    from storyforge.elaborate import _read_csv
    from storyforge.schema import pronoun_key
    path = os.path.join(project_dir, 'reference', 'characters.csv')
    ids: dict[str, set[str]] = {}
    pronouns: dict[str, str] = {}
    display: dict[str, str] = {}
    warnings: list[str] = []
    try:
        resolved = source.character_pronouns(project_dir)
    except source.SourceError as e:
        resolved = source.CastPronouns()
        warnings.append(f"the source's pronouns can't be read ({e}), so the gate doesn't "
                        f"check a pronoun speech tag of a character with none in "
                        f"characters.csv")
    warnings += [f"{n}: the gate doesn't check those characters' pronoun speech tags"
                 for n in resolved.notes]
    for row in _read_csv(path):
        name = (row.get('name') or '').strip()
        cid = (row.get('id') or '').strip() or name
        if not name:
            continue
        display[cid] = name
        for n in [name, cid, *(row.get('aliases') or '').split(';')]:
            if _words(n).strip():
                ids.setdefault(_words(n).strip(), set()).add(cid)
        key = pronoun_key(row.get('pronouns') or '')
        fallback = resolved.by_id.get(cid)
        if key == '' and fallback and fallback.origin == source.FROM_SOURCE:
            key = pronoun_key(fallback.value)
        elif key == '' and fallback and (fallback.note or fallback.problem):
            warnings.append(f"{name}: no pronouns in characters.csv or from the source "
                            f"({fallback.note or fallback.problem}), so the gate doesn't "
                            f"check a pronoun speech tag on their lines")
        if key:
            pronouns[cid] = key
        elif key is None:
            warnings.append(f"characters.csv: {name}'s pronouns ({row.get('pronouns')!r}) "
                            f"can't be read, so the gate doesn't check a pronoun speech tag "
                            f"on their scripted lines (validate blocks on this)")
    if not ids:
        warnings.insert(0, ('no reference/characters.csv' if not os.path.isfile(path)
                            else 'reference/characters.csv has no named characters')
                        + ': the gate checks no speaker of a scripted line')
    return Cast({n: frozenset(c) for n, c in ids.items()}, pronouns, display, tuple(warnings))


#: WARNING lines already logged in this process (`_warn_once`)
_WARNED: set[str] = set()


def _warn_once(lines) -> None:
    """Log each of `lines` as a WARNING, once per process (a run gates many
    scenes against the same characters.csv)."""
    from storyforge.common import log
    for line in lines:
        if line not in _WARNED:
            _WARNED.add(line)
            log(f'WARNING: {line}')


#: Words in a brief's speaker label that mean someone else in it speaks
#: (`Silas turns to Croy, who says:`)
_LABEL_SPEECH = frozenset('said says asked asks answered answers replied replies told tells '
                          'called calls whispered whispers murmured murmurs muttered mutters '
                          'shouted shouts added adds repeated repeats who'.split())


def _name_at(words: list[str], i: int, cast: Cast) -> tuple[int, frozenset[str]]:
    """The longest name in `cast` starting at `words[i]`, of any length
    (`Cast.longest`: "Ghost of Christmas Past"): its length and ids, or (0,
    empty)."""
    for n in range(min(cast.longest, len(words) - i), 0, -1):
        found = cast.ids.get(' '.join(words[i:i + n]))
        if found:
            return n, found
    return 0, frozenset()


def _named(text: str, cast: Cast) -> tuple[str | None, str]:
    """The one character a speaker label (`text`) names, and why not
    (`Scripted.why`) when it names none with confidence: it must start
    with a name or alias (`_name_at`) that only one character has, not a
    possessive ("Lena's warning" may be about someone else's line), not
    with another name next to it (`Thomas and Elena`, `Silas, Croy`), and
    no other name or pronoun later in it may come with a speech verb or
    "who" (`Silas turns to Croy, who says`)."""
    words = _words(text).split()
    # "— and Croy:", "then Silas:": the label of a line after another
    while len(words) > 1 and words[0] in _LABEL_JOINS:
        words = words[1:]
    n, found = _name_at(words, 0, cast)
    if not n:
        # A label that starts like a name (a capital) but names no one in
        # characters.csv is said as such: "the brief names no speaker" would
        # be wrong (#513's review, SF-4). Lowercase is narration ("— though
        # he knew", "told Thomas:")
        label = ' '.join(text.split())
        label = re.sub(r'^(?:(?:and|then)\s+)+', '', label, flags=re.I)
        named_like = label[:1].isupper()
        return (None, _not_in_cast(label)) if words and named_like else (None, _NO_LABEL)
    if len(found) != 1:
        return None, _SHARED
    rest = words[n:]
    if rest[:1] == ['s'] or _name_at(rest, 0, cast)[0] or (
            rest[:1] in (['and'], ['or']) and _name_at(rest, 1, cast)[0]):
        return None, _UNCLEAR
    for i in range(len(rest)):
        m = _name_at(rest, i, cast)[0] or (1 if rest[i] in _PRONOUNS else 0)
        if m and rest[i + m:i + m + 1] and rest[i + m] in _LABEL_SPEECH:
            return None, _UNCLEAR
    return next(iter(found)), ''


def _clauses(text: str) -> list[str]:
    """`text` cut where a clause ends: a full, question or exclamation
    stop followed (past any closing brackets or quote marks) by a space,
    a dash or the end (`(Pause. Rook shifts.) Maren`), but not one after
    a title (`brief_names._ABBREVIATIONS`, any case: `Sgt. Croy`); an
    ellipsis; | / ; or a line break."""
    from storyforge.brief_names import _ABBREVIATIONS
    out, start = [], 0
    for m in re.finditer(r'\.\.\.|…|[.!?]+[)\]"”’\'*_]*(?=\s|$|—|–)|[|/;\n]', text):
        if m.group().startswith('.') and not m.group().startswith('..'):
            word = re.search(r'(\w+)$', text[:m.start()])
            if word and word.group(1).lower() in _ABBREVIATIONS:
                continue
        out.append(text[start:m.start()])
        start = m.end()
    out.append(text[start:])
    return out


_DASH = r'(?:—|–|--?)'


def _label_speaker(before: str, after: str, cast: Cast) -> tuple[str | None, str]:
    """The character a brief gives a quoted span to, from the text around
    it in its item, and why not (`Scripted.why`) when there is none:
    either the last clause (`_clauses`) of the text before it, when that
    ends in a colon (`Dorren privately: "..."`, `(Pause. Rook shifts.)
    Maren: "..."`), or the first clause of the text after it, when that
    starts with a dash and doesn't end in a colon, which would make it the
    next line's label (`"..." — Lena`). The label must name one character
    with confidence (`_named`); a label holding a spaced dash (`Talia,
    afraid — and he hears himself:`) doesn't, nor does one that starts with
    anything but a name (`Council:`, `Spoken to the grave:`; `Cora hears:`
    still names Cora). Two labels that disagree name no one; one that
    names no one doesn't count against one that does (`Council: "..." —
    Thomas` is Thomas's). A wrong speaker here would send the brief's own
    words to the fix (the mended-bridle failure), so whatever is in doubt
    has no speaker, and is matched as before. Backslashes (escaped quotes
    in some briefs) are ignored."""
    if not cast.ids:
        return None, _NO_CAST
    labels = []
    before = before.replace('\\', '').strip()
    if before.endswith(':'):
        labels.append(re.sub(rf'^\s*{_DASH}\s*', '', _clauses(before[:-1])[-1]))
    after = _clauses(after.replace('\\', ''))[0]
    dash = re.match(rf'\s*{_DASH}\s*(.*)', after, re.S)
    if dash and not after.strip().endswith(':'):
        labels.append(dash.group(1))
    if not labels:
        return None, _NO_LABEL
    read = [(None, _UNCLEAR) if re.search(rf'\s{_DASH}\s', label) else _named(label, cast)
            for label in labels]
    named = {who for who, _ in read if who}
    if len(named) == 1:
        return named.pop(), ''
    if named:
        return None, _UNCLEAR
    return None, next((why for _, why in read if why != _NO_LABEL), _NO_LABEL)


def _brief_lines(project_dir: str, scene_id: str, cast: Cast | None = None) -> list[Scripted]:
    """The words the scene's brief scripts (`checker.PROMISE_FIELDS`), as
    phrases: each quoted span of an item, with the speaker the brief gives
    it (`_label_speaker`; `cast`: the characters, read when not given), and
    a `key_dialogue` item that quotes nothing, whole and with no speaker
    (a `Name:` label naming a character is taken off, so the phrase can
    match the prose, but not read as its speaker: quote the line to label
    it). An unquoted action or outcome is a paraphrase, not words
    the prose must use, so it isn't one. A `must:` marker (#642) is not
    part of an item. Phrases under `_MIN_BRIEF_WORDS` words are left out.
    A scene with no brief row scripts nothing."""
    from storyforge.checker import PROMISE_FIELDS
    from storyforge.elaborate import get_scene
    from storyforge.must import items
    scene = get_scene(scene_id, os.path.join(project_dir, 'reference')) or {}
    lines: list[Scripted] = []
    holder = [cast]
    for col in PROMISE_FIELDS:
        for item in items(scene.get(col) or ''):
            lines += _item_lines(project_dir, col, item.text, holder)
    return [p for p in lines if _count(_words(p.text)) >= _MIN_BRIEF_WORDS]


def _item_lines(project_dir: str, col: str, item: str,
                holder: list['Cast | None']) -> list[Scripted]:
    """`_brief_lines` for one item of `col` (its marker already off), short
    phrases included. `holder[0]` is the cast, read into it when first
    needed."""
    def cast() -> Cast:
        if holder[0] is None:
            holder[0] = _cast(project_dir)
        return holder[0]
    if not item:
        return []
    spans = list(re.finditer(r'"([^"]+)"|“([^”]+)”', item))
    if not spans:
        if col != 'key_dialogue':
            return []
        label = re.match(r'\s*([^:]{1,80}):\s*(\S.*)$', item, re.S)
        if label and _named(label.group(1), cast())[0]:
            item = label.group(2)
        return [Scripted(item, None, _NO_QUOTES)]
    out = []
    for i, m in enumerate(spans):
        before = item[spans[i - 1].end() if i else 0:m.start()]
        after = item[m.end():spans[i + 1].start() if i + 1 < len(spans) else len(item)]
        who, why = _label_speaker(before, after, cast())
        out.append(Scripted(m.group(1) or m.group(2), who, why))
    return out


def _brief_phrases(project_dir: str, scene_id: str) -> list[str]:
    """The words the scene's brief scripts (`_brief_lines`), without their
    speakers."""
    return [p.text for p in _brief_lines(project_dir, scene_id)]


#: A speech tag that may split a scripted line (`_is_speech_tag`): one of
#: these verbs with a pronoun or a character's name, nothing else
_SPEECH_VERBS = frozenset('said says asked asks answered replied told called whispered '
                          'murmured muttered shouted added repeated'.split())
#: Speech verbs whose object is the listener: only after the speaker
#: ("Thomas told", never "told Thomas")
_LISTENER_VERBS = frozenset({'told'})
_PRONOUNS = frozenset('he she they i we you'.split())
#: Quote marks a scripted line is spoken between: double quotes, straight or
#: curly, and curly single quotes (a closing ’ followed by a letter is an
#: apostrophe, not a mark)
_QUOTE_MARKS = re.compile(r'["“”‘]|’(?!\w)')


def _tag_speaker(text: str, names: frozenset[str] | set[str]) -> str | None:
    """Who `text` names when it is only a speech tag: a speech verb
    (`_SPEECH_VERBS`) and a pronoun or a character's name (`names`, of any
    length), either order, punctuation aside ("he said",
    "said Thomas"; "told" only after its speaker, `_LISTENER_VERBS`), as
    `_words` without the padding ("he", "thomas"). None when it isn't one:
    an adverb, a place or anything else in it makes it narration, which may
    hold the error."""
    words = _words(text).split()
    if not 2 <= len(words) <= _longest(names) + 1:
        return None
    for verb, who, first in ((words[0], words[1:], True), (words[-1], words[:-1], False)):
        if first and verb in _LISTENER_VERBS:
            continue
        if verb in _SPEECH_VERBS and (
                (len(who) == 1 and who[0] in _PRONOUNS) or ' '.join(who) in names):
            return ' '.join(who)
    return None


def _is_speech_tag(text: str, names: frozenset[str] | set[str]) -> bool:
    """Whether `text` is only a speech tag (`_tag_speaker`)."""
    return _tag_speaker(text, names) is not None


def _split_parts(quote: str,
                 names: frozenset[str] | set[str] = frozenset()) -> tuple[str, list[str]] | None:
    """`quote` as one line the prose split with speech tags (`"Left hand on
    the case," he said. "Right hand free."`): its spoken words, and who each
    tag between them names (`_tag_speaker`). There must be two or more
    spoken parts, each tag between them only a speech tag, and no words
    before the first part or after the last. Otherwise None: narration
    before or after a line, or a tag with anything else in it, may be where
    the error is. Both readings of its quote marks are tried (a quote can
    start mid-line, so its first mark may close a line)."""
    segments = _QUOTE_MARKS.split(quote.replace('\r\n', '\n'))
    for parity in (0, 1):
        spoken = [x for i, x in enumerate(segments) if i % 2 == parity]
        told = [(i, x) for i, x in enumerate(segments) if i % 2 != parity]
        tags = [x for i, x in told if 0 < i < len(segments) - 1]
        ends = [x for i, x in told if not 0 < i < len(segments) - 1]
        who = [_tag_speaker(x, names) for x in tags]
        if (tags and sum(1 for x in spoken if _words(x).strip()) >= 2
                and None not in who
                and not any(_words(x).strip() for x in ends)):
            return ' '.join(spoken), who
    return None


def _split_line(quote: str, names: frozenset[str] | set[str] = frozenset()) -> str | None:
    """The spoken words of `quote` when it is one line the prose split with
    speech tags (`_split_parts`), else None."""
    parts = _split_parts(quote, names)
    return parts[0] if parts else None


#: The pronouns a speech tag is checked against the speaker's
#: (characters.csv `pronouns`): "I", "we" and "you" depend on who narrates
_CHECKED_PRONOUNS = frozenset({'he', 'she', 'they'})


def _tag_fits(who: str, speaker: str | None, cast: Cast) -> bool:
    """Whether a speech tag naming `who` (`_tag_speaker`) can be the brief's
    `speaker`. A name or alias fits when one of the characters it names is
    the speaker (a shared name fits each of them). "he", "she" or "they"
    fits unless the speaker's pronouns are known (`Cast.pronouns`) and are
    another. Anything that can't be told fits: no speaker in the brief,
    "I", "we", "you", or a speaker with no pronouns known."""
    if speaker is None:
        return True
    if who in _PRONOUNS:
        known = cast.pronouns.get(speaker)
        return who not in _CHECKED_PRONOUNS or not known or who == known
    return speaker in cast.ids.get(who, frozenset())


def _speaker_note(line: Scripted, tags: list[str], cast: Cast) -> str:
    """Whether the speaker of a split line matched to `line` was checked,
    for the report: `speaker checked: <name>` when every tag (`tags`) was
    told against the brief's speaker, else `speaker not checked: <why>`."""
    if line.speaker is None:
        return f'speaker not checked: {line.why}'
    name = cast.display.get(line.speaker, line.speaker)
    for who in tags:
        if who in _PRONOUNS and who not in _CHECKED_PRONOUNS:
            return f'speaker not checked: the tag says "{who}"'
        if who in _PRONOUNS and line.speaker not in cast.pronouns:
            return f'speaker not checked: {name}\'s pronouns are not known'
    return f'speaker checked: {name}'


def _plan_conflict(quote: str, phrases: list[str | Scripted], cast: Cast) -> str | None:
    """`_is_plan_conflict`'s verdict with the reason for the report: None
    when the quote isn't the brief's words, else whether the speaker was
    checked (`_speaker_note`; a quote no tag splits has none to check). Of
    several phrases that match, the note is the first one's that wasn't
    checked: the conflict was set aside without the check."""
    lines = [p if isinstance(p, Scripted) else Scripted(p) for p in phrases]
    split = _split_parts(quote, cast.names)
    if split is not None:
        lines = [p for p in lines if all(_tag_fits(w, p.speaker, cast) for w in split[1])]

    def hits(text: str, within: bool = False) -> list[Scripted]:
        q = _words(text)
        n = _count(q)
        if n < _MIN_BRIEF_WORDS:
            return []
        return [x for x in lines
                if q in _words(x.text) or (not within and _words(x.text) in q
                                           and 2 * _count(_words(x.text)) >= n)]
    found = hits(quote)
    # a split line's spoken words must all be the brief's: with the tag set
    # aside, nothing else in the quote may be (the error could be there)
    if split is not None:
        found += [x for x in hits(split[0], within=True) if x not in found]
    if not found:
        return None
    if split is None:
        return 'speaker not checked: no speech tag splits the quote'
    notes = [_speaker_note(x, split[1], cast) for x in found]
    return next((n for n in notes if n.startswith('speaker not')), notes[0])


def _is_plan_conflict(quote: str, phrases: list[str | Scripted], cast: Cast) -> bool:
    """Whether a contradiction's `quote` is the brief's own words: the
    quote lies within a scripted phrase, or a scripted phrase makes up at
    least half of it (a short scripted line inside a long quote whose error
    is elsewhere is not one). A quote under `_MIN_BRIEF_WORDS` words is
    never one.

    A scripted line the prose split with a speech tag (`"Left hand on the
    case," he said. "Right hand free."`) is matched on its spoken words
    (`_split_parts`; `cast`: the characters a tag may name): the
    mended-bridle run (2026-11-03) sent such a line, the brief's own, to
    the fix as a contradiction with a later scene, and the fix rewrote the
    scene to match that scene's error. Narration before or after a line is
    not taken out (`"...," said the dead man.`), and a tag with anything
    but a speaker and a speech verb is narration: either may hold the
    error. So is a tag naming someone not in characters.csv: the line isn't
    split, and isn't set aside. A split line's spoken words must all lie
    within one scripted phrase.

    The speaker each tag of a split line names must fit the one the brief
    gives the phrase (`Scripted.speaker`, `_tag_fits`): "Emmett said" on
    a line the brief gives Thomas is not the brief's words, and goes to the
    fix (#504's known limit). So is "she said" when Thomas's pronouns are
    known to be he. Not checked, so matched as before: a phrase the brief
    gives no one (a plain string, or `Scripted` with no speaker), "I",
    "we" or "you", a pronoun tag when the speaker's pronouns aren't known,
    and a tag after a line that isn't split (`"...," she said`, matched
    only by the half rule). The report says which (`_plan_conflict`)."""
    return _plan_conflict(quote, phrases, cast) is not None


# ============================================================================
# The book before a pass: what an error already there is (Ben, 2026-11-01)
# ============================================================================

@dataclass
class Snapshot:
    """The book before a pass (`snapshot`): the baseline against which the
    gate tells an error the pass made from one already there (`inherited`)."""
    #: scene id → prose, for the scenes whose prose is a baseline: readable,
    #: and not waiting on the gate
    scenes: dict[str, str] = field(default_factory=dict)
    #: reference file name → sha1 of its bytes (None: two files share the name)
    files: dict[str, str | None] = field(default_factory=dict)
    #: scene id → why it isn't in `scenes`
    left_out: dict[str, str] = field(default_factory=dict)


def _sha1(path: str) -> str | None:
    import hashlib
    try:
        with open(path, 'rb') as f:
            return hashlib.sha1(f.read()).hexdigest()
    except OSError:
        return None


def snapshot(project_dir: str) -> Snapshot:
    """The book as it is now, taken before a command writes prose and
    passed to the gate as `before=`. Take it once per run: a scene the run
    rewrites before another is gated then counts as changed.

    A scene listed in working/gate-pending.csv is left out (#480's review):
    its prose didn't pass the gate or wasn't checked, so a retry that keeps
    its error must not pass it as inherited. With the list unreadable every
    scene is left out. A scene that isn't UTF-8 is left out too."""
    snap = Snapshot()
    try:
        waiting = pending(project_dir)
    except GateError as e:
        waiting, unreadable = None, str(e)
    scenes_dir = os.path.join(project_dir, 'scenes')
    names = sorted(os.listdir(scenes_dir)) if os.path.isdir(scenes_dir) else []
    for name in names:
        if not name.endswith('.md'):
            continue
        sid = name[:-3]
        if waiting is None:
            snap.left_out[sid] = f'the pending list is unreadable: {unreadable}'
            continue
        if sid in waiting:
            snap.left_out[sid] = f'waiting on the gate ({waiting[sid]["command"]})'
            continue
        try:
            with open(os.path.join(scenes_dir, name), encoding='utf-8') as f:
                snap.scenes[sid] = f.read()
        except (OSError, UnicodeDecodeError) as e:
            snap.left_out[sid] = f'unreadable ({type(e).__name__})'
    ref_dir = os.path.join(project_dir, 'reference')
    for root, _, files in os.walk(ref_dir):
        for name in files:
            digest = _sha1(os.path.join(root, name))
            snap.files[name] = None if name in snap.files else digest
    return snap


def _unchanged_since(project_dir: str, snap: Snapshot, source: str, scene_id: str,
                     established_quote: str) -> bool:
    """Whether the established side of a contradiction is as it was in
    `snap` (#480's review: a contradiction is new when either side changed).
    A scene other than this one: its file is unchanged. This scene: the
    established quote was in it. A reference file or the calendar: its
    bytes are unchanged. The ledger, or anything unknown: no."""
    source = (source or '').strip()
    if not source:
        return False
    if source == scene_id:
        return _quoted_in(established_quote, snap.scenes.get(scene_id, ''))
    if source in snap.scenes:
        try:
            with open(os.path.join(project_dir, 'scenes', f'{source}.md'),
                      encoding='utf-8') as f:
                return f.read() == snap.scenes[source]
        except (OSError, UnicodeDecodeError):
            return False
    old = snap.files.get(source)
    if old is None:
        return False
    found = [os.path.join(root, source) for root, _, files
             in os.walk(os.path.join(project_dir, 'reference')) if source in files]
    return len(found) == 1 and _sha1(found[0]) == old


# ============================================================================
# Advisory promises and `must` beats (#642)
# ============================================================================

def _brief_row(project_dir: str, scene_id: str) -> dict[str, str]:
    from storyforge.elaborate import get_scene
    return get_scene(scene_id, os.path.join(project_dir, 'reference')) or {}


def _must_beats(scene: dict[str, str]) -> dict[str, list]:
    """The brief's `must` items (`must.Item`s that name a beat), by field."""
    from storyforge.must import MUST_FIELDS, must_items
    return {col: must_items(scene.get(col) or '') for col in MUST_FIELDS}


def _misplaced_must(scene: dict[str, str]) -> list[str]:
    """`GateResult.misplaced_must` for the brief row `scene`: `field: item`
    for each item whose `must:` marks nothing (`must.misplaced`), the
    author-note columns included (a `must:` there requires nothing; #695)."""
    from storyforge.checker import PROMISE_FIELDS, REGISTRY_PROMISE_FIELDS
    from storyforge.elaborate import AUTHOR_NOTE_COLUMNS
    from storyforge.must import misplaced
    cols = dict.fromkeys((*PROMISE_FIELDS, *REGISTRY_PROMISE_FIELDS, *AUTHOR_NOTE_COLUMNS))
    return [f'{col}: {item}' for col in cols
            for item in misplaced(scene.get(col) or '', col)]


def _bare_must(scene: dict[str, str]) -> list[str]:
    """`GateResult.bare_must` for the brief row `scene`."""
    from storyforge.must import MUST_FIELDS, bare_markers
    return [f'{col} ({n})' for col in MUST_FIELDS
            for n in [bare_markers(scene.get(col) or '')] if n]


def _is_must(f: Finding, scene: dict[str, str], beats: dict[str, list]) -> bool:
    """Whether the broken promise `f` is of a `must` beat. With no `must`
    beat in the brief, never. Otherwise, in this order:

    1. a quote that is one whole item of the brief is that item, marked or
       not (its own field first, then any promise field);
    2. a quote found in its own field when that field takes no marker
       (`outcome`, the registry fields: a verified promise of one) is not;
    3. a quote that names a `must` beat (`must.names_beat`) is;
    4. a quote that names an unmarked item of its own field (of any field,
       for a made-up id) is not;
    5. anything else (a paraphrase, a short partial quote, words that name
       no item) is: in doubt, `must`. A wrong stop costs a look; a wrong
       pass loses the author's beat (#642's review TD-1, CR-2)."""
    from storyforge.checker import PROMISE_FIELDS, REGISTRY_PROMISE_FIELDS
    from storyforge.must import MUST_FIELDS, items, names_beat, strip_marker
    if not any(beats.values()):
        return False
    said = f.established_quote or ''
    quote = _words(strip_marker(said))
    fields = list(PROMISE_FIELDS) + list(REGISTRY_PROMISE_FIELDS)
    own = [f.fact_id] if f.fact_id in fields else []
    if quote.strip():
        for col in own + [c for c in fields if c not in own]:
            for item in items(scene.get(col) or ''):
                if _words(item.text) == quote:
                    return item.beat
        if own and own[0] not in MUST_FIELDS and quote in _words(scene.get(own[0]) or ''):
            return False
    if any(names_beat(said, b.text) for col in MUST_FIELDS for b in beats.get(col, [])):
        return True
    return not any(names_beat(said, item.text) for col in (own or fields)
                   for item in items(scene.get(col) or '') if not item.must)


#: #788: the halts a plan can call for: a scene that changes a fixed fact
_PLANNABLE_HALTS = ('supersedes-fixed', 'changes-fixed')


def _planned_change(project_dir: str, scene_id: str, fact: dict[str, str],
                    fixed: dict[str, str], rows: list[dict[str, str]],
                    scene: dict[str, str] | None = None) -> str:
    """Why the scene's plan calls for `fact`, which changes the binding
    `fixed` fact `fixed` ('' when it doesn't; #788): a plan fact (origin
    `plan`, binding or planned) the brief sets in this scene (its row's
    scene, or listed in the brief's `knowledge_out` or
    `physical_state_out`) about the subject of either, or a `must:` beat
    of the brief that `fact`'s quote or statement names
    (`must.names_beat`). `scene`: the brief row (read when None)."""
    from storyforge.must import MUST_FIELDS, names_beat
    if scene is None:
        scene = _brief_row(project_dir, scene_id)
    subjects = {(r.get('subject') or '').strip().lower() for r in (fact, fixed)} - {''}
    listed = {i.strip() for col in ('knowledge_out', 'physical_state_out')
              for i in (scene.get(col) or '').split(';') if i.strip()}
    for r in rows:
        rid = (r.get('id') or '').strip()
        if (r.get('origin') == 'plan' and r.get('status') in ('binding', 'planned')
                and rid != (fixed.get('id') or '').strip()
                and ((r.get('scene_id') or '').strip() == scene_id or rid in listed)
                and (r.get('subject') or '').strip().lower() in subjects):
            return f'the plan sets {rid} in this scene ("{r.get("statement", "")}")'
    for col in MUST_FIELDS:
        for beat in _must_beats(scene).get(col, []):
            if any(names_beat(fact.get(k) or '', beat.text) for k in ('quote', 'statement')):
                return f'the brief\'s must: beat in {col} ("{beat.text}")'
    return ''


def _mark_planned(project_dir: str, scene_id: str, halts: list[audit.Halt],
                  proposed: list[dict[str, str]],
                  rows: list[dict[str, str]]) -> list[audit.Halt]:
    """`halts`, each one the scene's plan calls for (`_planned_change`)
    marked with why (`Halt.planned`, #788): it still stops the scene, but
    goes to the author (the fixed fact is likely mis-typed: `check
    --unfix`), never to the fix."""
    from dataclasses import replace
    if not any(h.kind in _PLANNABLE_HALTS for h in halts):
        return halts
    by_id = {(r.get('id') or '').strip(): r for r in rows}
    facts = {(r.get('id') or '').strip(): r for r in proposed}
    scene = _brief_row(project_dir, scene_id)
    out = []
    for h in halts:
        fact, fixed = facts.get(h.fact_id), by_id.get(h.fixed_id)
        why = (_planned_change(project_dir, scene_id, fact, fixed, rows, scene)
               if h.kind in _PLANNABLE_HALTS and fact and fixed else '')
        out.append(replace(h, planned=why) if why else h)
    return out


def _set_up_here(project_dir: str, scene_id: str,
                 rows: list[dict[str, str]] | None = None) -> set[str]:
    """The binding registry facts (knowledge, physical) the ledger says
    `scene_id` sets up (#642's review CR-1): a broken promise of one stops
    the scene, for the prose is the fact's only evidence and later scenes
    are read against it as set up here. `rows`: the ledger (read when
    None)."""
    if rows is None:
        rows = ledger.load(project_dir)
    return {r['id'] for r in rows
            if (r.get('scene_id') or '').strip() == scene_id
            and r.get('status') == 'binding' and not ledger.is_commitment(r)
            and r.get('type') in ledger.VIEW_COLUMNS}


#: Why a broken promise stops the scene (`GateResult.promise_why`)
MUST_BEAT = 'the brief marks this beat must:'
SET_UP_HERE = ('the ledger sets up {id} in this scene, and later scenes are read against it: '
               'establish it in the prose, or move or reject the fact')


#: How many words of narration (a speech tag) may stand between two quoted
#: parts of a `must` line (`_verbatim_in`: `"Sing," he said, "goddess"`)
_TAG_GAP = 6

#: A quotation in the prose: straight or curly double quotes, within a
#: paragraph (its sentences are on lines of their own, `scene_layout`)
_QUOTATION = re.compile(r'"((?:[^"\n]|\n(?![ \t]*\n))+)"|“((?:[^”\n]|\n(?![ \t]*\n))+)”')


def _verbatim_in(line: str, prose: str) -> bool:
    """Whether the brief's `line` is in `prose` word for word (case,
    punctuation and spacing aside, `_found_in`), or split by speech tags:
    the words of consecutive quotations of one paragraph, joined, with at
    most `_TAG_GAP` words of narration between each two. Only narration
    outside the quotation marks counts as a tag: words inside a quotation
    are the line's own, so a line with words put inside it isn't the line
    (#642's review CR-3). A paragraph without double quotes (single-quoted
    dialogue, or none) is matched whole only."""
    if _found_in(line, prose):
        return True
    want = _words(line)
    if not want.strip():
        return False
    for para in re.split(r'\n\s*\n', prose):
        chain: list[str] = []
        end = None
        for m in _QUOTATION.finditer(para):
            if end is not None and _count(_words(para[end:m.start()])) > _TAG_GAP:
                if len(chain) > 1 and want in _words(' '.join(chain)):
                    return True
                chain = []
            chain.append(m.group(1) or m.group(2))
            end = m.end()
        if len(chain) > 1 and want in _words(' '.join(chain)):
            return True
    return False


def _line_forms(col: str, text: str) -> list[str]:
    """The ways an unquoted `key_dialogue` line may stand in the prose: as
    `_item_lines` gives it, and without a leading `Label:` it kept because
    the label names no one in characters.csv (a role: `The old man: ...`;
    #642's review T3)."""
    label = re.match(r'\s*([^:"“]{1,80}):\s*(\S.*)$', text, re.S)
    if col != 'key_dialogue' or not label:
        return [text]
    return [text, label.group(2)]


#: The code of a broken promise the gate finds by code (`_verbatim_findings`),
#: not the checker: a `must` line not in the prose word for word (#642's
#: review TD-5)
MUST_CODE = 'MST'


def _verbatim_findings(project_dir: str, scene_id: str, prose: str,
                       check: CheckResult,
                       short_lines: list[str] | None = None) -> list[Finding]:
    """A broken promise, found by code, for each `must` item of the brief
    whose scripted words (`_item_lines`: its quoted spans, or a
    `key_dialogue` line that quotes nothing; `_MIN_BRIEF_WORDS` words or
    more) aren't in `prose` word for word (`_verbatim_in`), unless the
    check already reported a broken promise of that item. A faithful
    adaptation marks the source lines it keeps verbatim this way (#642).
    An unquoted action is a paraphrase: the check judges whether it is
    kept. A scripted part under `_MIN_BRIEF_WORDS` words is too short to
    find by code: it goes into `short_lines` (`field: "words"`), for a
    NOTE, and is left to the check (#642's review CR-5). The findings'
    code is `MUST_CODE`."""
    from storyforge.must import names_beat
    scene = _brief_row(project_dir, scene_id)
    beats = _must_beats(scene)
    if not any(beats.values()):
        return []
    # only a reported promise that stays the must beat's covers it: one of
    # an unmarked item goes to advisory (#642's review SF-1, T1)
    reported = [f for f in check.findings + check.unverified
                if f.kind == 'broken-promise' and _is_must(f, scene, beats)]
    holder: list[Cast | None] = [None]
    out, short = [], []
    for col, items_ in beats.items():
        for item in items_:
            lines = _item_lines(project_dir, col, item.text, holder)
            short += [f'{col}: "{p.text}"' for p in lines
                      if _count(_words(p.text)) < _MIN_BRIEF_WORDS]
            lines = [p for p in lines if _count(_words(p.text)) >= _MIN_BRIEF_WORDS]
            missing = [p.text for p in lines
                       if not any(_verbatim_in(form, prose)
                                  for form in (_line_forms(col, p.text)
                                               if p.why == _NO_QUOTES else [p.text]))]
            if not missing or any(names_beat(f.established_quote, item.text)
                                  for f in reported):
                continue
            out.append(Finding(
                'broken-promise', MUST_CODE, '', '', item.raw, col,
                'the brief marks this beat must:, and the scene does not have its words '
                'word for word: ' + '; '.join(f'"{line}"' for line in missing)))
    if holder[0] is not None:
        _warn_once(holder[0].warnings)
    if short_lines is not None:
        short_lines[:] = short
    return out


def _classify(result: GateResult, project_dir: str, before: Snapshot | None,
              reported: list[dict[str, str]], prose: str = '',
              rows: list[dict[str, str]] | None = None) -> None:
    """Sort the check's verified contradictions into `inherited` and
    `plan_conflicts` (each set anew).

    Inherited: the error was in the book before this pass. Either its
    words (`_quoted_in`) were in the scene in `before` and its established
    side is unchanged since (`_unchanged_since`), or the author was already
    told of it (`reported`: the same source and quote, from
    working/gate-reported.csv), or (#631) it is a blocking finding against
    the scene itself in paragraphs of `prose` an accepted one was recorded
    on, unchanged since (`_accepted_blocking_covers`). Inherited comes
    first: an error the pass didn't make doesn't stop it, whatever its
    source.

    Plan conflict: its words are the brief's own (`_is_plan_conflict`;
    a split line's speech tags must fit the speaker the brief names).

    Broken promises and unverified findings are neither. A broken promise,
    verified or not, is `advisory` (#642) unless it is of a beat the brief
    marks `must:` (`_is_must`) or of a registry fact the ledger sets up in
    this scene (`_set_up_here`); those block, and `promise_why` says why.
    An advisory continuity check's finding (`continuity.is_advisory`) is
    `advisory` too, and neither inherited nor a plan conflict.
    `rows`: the ledger (read when None)."""
    from storyforge.continuity import is_advisory
    result.inherited, result.plan_conflicts, result.speaker_notes = [], [], []
    result.advisory, result.bare_must, result.promise_why = [], [], []
    result.misplaced_must = []
    if not result.check:
        return
    scene = _brief_row(project_dir, result.scene_id)
    beats = _must_beats(scene)
    result.bare_must = _bare_must(scene)
    result.misplaced_must = _misplaced_must(scene)
    here = _set_up_here(project_dir, result.scene_id, rows)
    for f in result.check.findings + result.check.unverified:
        if f.kind != 'broken-promise':
            continue
        if f.fact_id in here:
            result.promise_why.append((f, SET_UP_HERE.format(id=f.fact_id)))
        elif _is_must(f, scene, beats):
            result.promise_why.append((f, MUST_BEAT))
        else:
            result.advisory.append(f)
    result.advisory += [f for f in result.check.findings + result.check.unverified
                        if is_advisory(f)]
    old = before.scenes.get(result.scene_id) if before else None
    known = {(r['source'], _words(r['quote'])) for r in reported}
    phrases = None
    for f in result.check.findings:
        if f.kind != 'contradiction' or not f.scene_quote.strip() or is_advisory(f):
            continue
        if ((f.established_scene or '', _words(f.scene_quote)) in known
                or (old is not None and _quoted_in(f.scene_quote, old)
                    and _unchanged_since(project_dir, before, f.established_scene,
                                         result.scene_id, f.established_quote))
                or (prose and any(_accepted_blocking_covers(r, f, result.scene_id, prose)
                                  for r in reported))):
            result.inherited.append(f)
            continue
        if phrases is None:
            cast = _cast(project_dir)
            _warn_once(cast.warnings)
            phrases = _brief_lines(project_dir, result.scene_id, cast)
        note = _plan_conflict(f.scene_quote, phrases, cast)
        if note is not None:
            result.plan_conflicts.append(f)
            result.speaker_notes.append((f, note))


def _hold_back(result: GateResult, also: list[Finding] | None = None,
               prose: str = '', rows: list[dict[str, str]] | None = None) -> None:
    """Take out of `proposed` each commitment stating an inherited
    contradiction (its quote and the finding's overlap), so the ledger never
    records a fact the check showed contradicts the book (#480's review).
    `also`: more findings to hold back for (a provisional commit's, #556),
    matched wider, since the checker's quote and the fact's need not share
    words ("he seized thirty sleepers" against a fact quoting "thirty of the
    thanes"): a commitment is held back for one when its quote overlaps the
    finding's, lies in the same paragraph of `prose` as the finding's quote,
    or has the subject and type of the fact the finding says it
    contradicts (`_finding_subjects` over `rows`, the ledger). Those held
    for an inherited finding go to `held_back`, reported, and are not
    recorded. Those held for an `also` finding are recorded as disputed
    (#735: a false finding kept Pandarus's death out of the ledger): status
    `pending`, so nothing holds the book to them, and `reviewed` `HELD` +
    the finding's key, so `accept_blocked` brings them into force when the
    author accepts it. They go to `disputed` and `disputed_rows`, reported.

    A kept fact (`result.steady`: an earlier commitment read from a
    paragraph the prose has unchanged) is never held back (#632, iliad-teen:
    each `check --accept` dropped steady facts, which counted as changed and
    listed most of the book for a re-check): it is in the ledger already,
    and holding it back would change the ledger for a finding about words
    that didn't change. It goes to `kept_stating`, reported."""
    def overlaps(quote: str, f: Finding) -> bool:
        return bool(f.scene_quote) and _count(quote) >= _MIN_BRIEF_WORDS and (
            quote in _words(f.scene_quote) or _words(f.scene_quote) in quote)

    paras = [p for p in re.split(r'\n\s*\n', prose) if p.strip()] if prose else []

    def paragraph(quote: str) -> set[int]:
        return {i for i, p in enumerate(paras) if quote and _found_in(quote, p)}

    def subject(row: dict[str, str]) -> str:
        return (row.get('subject') or '').strip().casefold()

    wide = []
    for f in also or []:
        at = paragraph(f.scene_quote)
        # the finding's claim: its values, about the subjects of the facts
        # stating it (a quote overlapping it, or in its paragraph)
        stating = {subject(r) for r in result.proposed
                   if overlaps(_words(r.get('quote') or ''), f)
                   or (paragraph(r.get('quote') or '') & at)} - {''}
        wide.append((f, at, _finding_subjects(f, rows or []), _values(f.scene_quote), stating))
    keep = []
    # a source-backed contradiction whose earlier fact couldn't be found to
    # supersede is held back like an inherited one (`_source_supersede`)
    strict = result.inherited + list(result.source_unmatched)
    steady = set(result.steady)
    for row in result.proposed:
        quote = _words(row.get('quote') or '')
        hit = next((f for f in strict if overlaps(quote, f)), None)
        disputed = False
        if hit is None and wide:
            where = paragraph(row.get('quote') or '')
            key = (subject(row), row.get('type') or '')
            values = _values(f"{row.get('statement', '')} {row.get('quote', '')}")
            # #735's review CR-4: every finding it states, so it comes into
            # force only once each is accepted
            hits = [f for f, at, subjects, claim, stating in wide
                    if overlaps(quote, f) or (where & at)
                    or (key[0] and key in subjects)
                    # #556's review: the claim restated elsewhere ("412
                    # residents" three paragraphs on)
                    or (values & claim and (not stating or key[0] in stating))]
            hit = hits[0] if hits else None
            disputed = hit is not None
        if hit is None:
            keep.append(row)
        elif row.get('id') in steady:
            keep.append(row)
            result.kept_stating.append((row.get('statement', ''), hit))
        elif disputed:
            row['status'] = 'pending'
            row['reviewed'] = held_stamp(sorted({finding_key(f) for f in hits}))
            result.disputed.append((row.get('statement', ''), hit))
            result.disputed_rows.append(row)
        else:
            result.held_back.append((row.get('statement', ''), hit))
    result.proposed = keep


_UNITS = {w: n for n, w in enumerate(
    'zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen '
    'fifteen sixteen seventeen eighteen nineteen'.split())}
_TENS = {w: 10 * n for n, w in enumerate(
    'twenty thirty forty fifty sixty seventy eighty ninety'.split(), start=2)}
_SCALES = {'hundred': 100, 'thousand': 1000, 'million': 1_000_000}


def _values(text: str) -> set[int]:
    """The numbers `text` states, in digits or words ("four hundred and
    twelve" and "412" are both 412), for matching a claim restated in other
    words."""
    out: set[int] = set()
    total = current = 0
    seen = False
    for w in re.findall(r"[a-z]+|\d[\d,]*", text.lower()):
        if w[0].isdigit():
            out.add(int(w.replace(',', '')))
            continue
        if w in _UNITS:
            current += _UNITS[w]
        elif w in _TENS:
            current += _TENS[w]
        elif w in _SCALES:
            if _SCALES[w] == 100:
                current = max(current, 1) * 100
            else:
                total += max(current, 1) * _SCALES[w]
                current = 0
        elif w == 'and' and seen:
            continue
        else:
            if seen:
                out.add(total + current)
            total = current = 0
            seen = False
            continue
        seen = True
    if seen:
        out.add(total + current)
    return out


def _finding_subjects(f: Finding, rows: list[dict[str, str]]) -> set[tuple[str, str]]:
    """The (subject casefolded, type) of the ledger facts `f` says the
    scene contradicts: the one its `fact_id` names, or the commitments of
    its established scene whose quote holds the established words (or is
    held by them)."""
    out = set()
    for r in rows:
        subject = (r.get('subject') or '').strip().casefold()
        if not subject:
            continue
        if f.fact_id and r.get('id') == f.fact_id:
            out.add((subject, r.get('type') or ''))
        elif (f.established_scene and (r.get('scene_id') or '').strip() == f.established_scene
              and f.established_quote and r.get('quote')
              and (_found_in(r['quote'], f.established_quote)
                   or _found_in(f.established_quote, r['quote']))):
            out.add((subject, r.get('type') or ''))
    return out


def _apply_source(result: GateResult, project_dir: str, scene_id: str, prose: str,
                  order: dict[str, int], log_dir: str, model: str,
                  old_rows: list[dict[str, str]] = ()) -> None:
    """The source check (`gate_source`, #557) for a faithful adaptation:
    report the proposed facts the source contradicts (`source_departs`,
    #742: still committed), take the verified contradictions with an
    earlier scene the source backs this scene on out of the findings
    (`source_backed`), and list for the author each other blocking finding
    the source narrates the same way (`source_has_it`, #742: it still
    blocks; `note_source_has_it`). Says in `source_notes` why it didn't
    run, or what it didn't rule on; a failed call is a note, never a stop.

    Cost (#557's review): only the proposed facts new to the scene (no
    earlier commitment of it states the same fact, `ledger.fact_key`) are
    sent, and with none of those, no contradiction and no other blocking
    finding to rule on there is no call (a re-check of an unchanged scene);
    a fix round whose facts and findings are what an earlier run of this
    process sent reuses its ruling (`gate_source.review`'s memo), and so
    does one with the same facts and fewer findings (#736: a fix's re-check
    carries its facts, `gate_source._from_earlier`)."""
    from storyforge import gate_source
    ctx = gate_source.setup(project_dir)
    if ctx is None:
        return
    if ctx.skip:
        result.source_notes.append(f'not checked against the source: {ctx.skip}')
        return
    result.source_notes.extend(ctx.warnings)
    if scene_id not in ctx.refs:
        result.source_notes.append('not checked against the source: the scene is invented '
                                   'or not mapped in reference/source-map.csv')
        return
    at = order.get(scene_id, 0)
    contradictions = [f for f in result.findings
                      if f.kind == 'contradiction' and not _among(f, result.plan_conflicts)
                      and f.established_scene in order and order[f.established_scene] < at]
    # #742: the scene's own blocking and possession findings, and those
    # against the ledger, a bible or the calendar, verified or not
    blocking = [f for f in result.findings + result.unverified
                if f.kind == 'contradiction' and not _among(f, contradictions)
                and not _among(f, result.plan_conflicts)]
    known = {ledger.fact_key(r) for r in old_rows}
    try:
        listed = scene_id in source_fixes(project_dir)
    except GateError as e:
        result.source_notes.append(str(e))
        listed = False
    # #742's review (SF-1): a fact the source contradicts is committed, so
    # it is never new again; while the scene is listed to fix toward the
    # source every fact is sent, so the listing comes off only once each
    # departure is gone or re-ruled (`_keep_superseded`)
    fresh = [i for i, r in enumerate(result.proposed)
             if listed or ledger.fact_key(r) not in known]
    # #749's review CR-2: the claims in speech new to the scene go too, after
    # the facts; one the source tells otherwise is advisory, never blocking
    claims = [c for c in result.claims if listed or ledger.fact_key(c) not in known]
    if not fresh and not claims and not contradictions and not blocking:
        return
    try:
        review = gate_source.review(project_dir, scene_id, prose,
                                    [result.proposed[i] for i in fresh] + claims,
                                    contradictions, model=model,
                                    log_file=gate_source.log_file(log_dir, scene_id), ctx=ctx,
                                    findings=blocking)
    except gate_source.SourceReviewError as e:
        result.source_notes.append(f'not checked against the source: {e}')
        return
    result.source_notes.extend(review.notes)
    result.source_ruled = bool(fresh) and review.ruled >= set(range(len(fresh)))
    result.source_departs = [(result.proposed[fresh[i]].get('statement', ''), why)
                             for i, why in review.departs if i < len(fresh)]
    result.claim_departs = [(claims[i - len(fresh)].get('statement', ''), why)
                            for i, why in review.departs if i >= len(fresh)]
    if result.claim_departs:
        try:
            note_source_has_it(project_dir, scene_id, prose, [
                (f'a claim in speech the source tells otherwise (kept as said): '
                 f'"{_one_line(st)}"', '', why) for st, why in result.claim_departs])
        except (GateError, OSError) as e:
            result.source_notes.append(f'{SOURCE_NOTES_PATH} could not be updated ({e}): the '
                                       f'claims in speech the source tells otherwise are only '
                                       f'in this report')
    result.source_backed = [(contradictions[i], why) for i, why in review.backs_scene]
    result.source_has_it = [(blocking[i], quote, why) for i, quote, why in review.has_it]
    if result.source_has_it:
        try:
            note_source_has_it(project_dir, scene_id, prose, result.source_has_it)
        except (GateError, OSError) as e:
            result.source_notes.append(f'{SOURCE_NOTES_PATH} could not be updated ({e}): the '
                                       f'source passages below are only in this report')


def has_commitments(project_dir: str, scene_id: str) -> bool:
    """Whether the ledger holds commitments from `scene_id`'s prose."""
    return any(ledger.is_commitment(r) and (r.get('scene_id') or '').strip() == scene_id
               for r in ledger.load(project_dir))


def gate_scene(project_dir: str, scene_id: str, *, command: str, prose: str | None = None,
               log_dir: str, extract_model: str | None = None,
               check_model: str | None = None,
               introduced_by: str | None = None,
               before: Snapshot | None = None,
               standing: 'GateResult | None' = None,
               carry: 'GateResult | None' = None,
               open_from: 'GateResult | None' = None,
               hold_slips: bool = False,
               pinned: dict | None = None) -> GateResult:
    """`_gate_scene`, with its model calls (extraction, the persistence check,
    every reading of the check) written to the cost ledger as `gate` rows for
    the scene, whether or not it finishes (F-151)."""
    from storyforge import api
    with api.metered() as meter:
        try:
            return _gate_scene(project_dir, scene_id, command=command, prose=prose,
                               log_dir=log_dir, extract_model=extract_model,
                               check_model=check_model, introduced_by=introduced_by,
                               before=before, standing=standing, carry=carry,
                               open_from=open_from, hold_slips=hold_slips, pinned=pinned)
        finally:
            _log_spend(meter, project_dir, 'gate', scene_id)


def _log_spend(meter, project_dir: str, operation: str, scene_id: str) -> None:
    """Write a meter's spend to the cost ledger; a failed write is a warning,
    never an error that hides the gate's own."""
    from storyforge.common import log
    try:
        meter.log(project_dir, operation, scene_id)
    except Exception as e:
        log(f'WARNING: could not log the cost of {operation} {scene_id}: {e}')


def _gate_scene(project_dir: str, scene_id: str, *, command: str, prose: str | None = None,
                log_dir: str, extract_model: str | None = None,
                check_model: str | None = None,
                introduced_by: str | None = None,
                before: Snapshot | None = None,
                standing: 'GateResult | None' = None,
                carry: 'GateResult | None' = None,
                open_from: 'GateResult | None' = None,
                hold_slips: bool = False,
                pinned: dict | None = None) -> GateResult:
    """Extract, halt, check and (if all clear) commit `scene_id`'s prose:
    `prose`, or the scene file when None. `command` is the command that
    wrote the prose (one of `GATE_COMMANDS`), recorded as the new rows'
    `introduced_by` and as the audit log's command.

    A redraft is extracted and checked against the ledger without its
    earlier version's commitments, and the `resolves` that version set on
    earlier commitments are cleared (this version's `ends` set them again).
    A `resolves` on a registry state is never touched: a state the plan sets
    up in this scene and the prose ends in it too is ended by a commitment
    of the scene that supersedes it (`ENDS_HERE`, `_apply_ends`; #734), so
    replacing the scene's commitments clears it like any other.
    `introduced_by` (default `command`) is what the new rows record; a
    re-check keeps the prose's writer.

    `standing` (#734) is an earlier run of the same prose whose blocking
    findings still stand: each one this run's check didn't make again
    (`_persists`) is added to its own, so a re-extraction beside findings
    re-reads the facts without a re-roll of the check passing the prose.

    `carry` (#736) is the run of the prose before a fix: its extraction's
    replies stand for this prose's when no fact's quote was changed
    (`_carry_of`, `_extract`), so there is no extraction or persistence
    call; the rows are made again from them by code, and the check, the
    blocking read and the typed state read this prose as ever.

    `pinned` (#788) is an eval's frozen extraction of this prose
    (`pinned_extraction`'s dict): its replies stand for the extraction and
    persistence calls, which aren't made, so an eval measuring the layers
    after extraction doesn't re-record them when extraction's prompt
    changes. Never passed outside the evals.

    `open_from` (#738) is an earlier run of this process whose open reading
    stands for this one under `tandem` (the run before a fix, a re-roll or
    a re-extraction): no open reading is made, and its open findings are
    carried (`_carry_open`). Ignored by the other methods, and by a run
    with no open reading behind it (`open_findings` None), which reads.

    `hold_slips` marks a reading again of prose an earlier run of this
    process stopped on the extractor's quote slips (#598's re-extraction):
    a fact it misquotes, or gives no quote, is held back instead of stopping
    the scene (`_hold_slips`; E4's re-record, 2026-11-27: the second reading
    made the first's slip again in each of three scenes). So does a run
    whose `carry` held slips back (a fix's re-check after it).

    `before` is the book before the pass that wrote `prose` (`snapshot`;
    None: a new scene or advisor mode; a re-check through `gate_unchanged`
    passes the scene's own gated prose alone, `own_snapshot`, #631). On a
    re-check of the prose the scene was last committed with, whose gate had
    a blocking read, the blocking read is skipped (`blocking_read_before`,
    #631), and the log says whether it ran and why. A contradiction that
    was already there is `inherited`: reported, not blocking (Ben,
    2026-11-01: a pass doesn't stop on an error it didn't make), and so is
    one already in working/gate-reported.csv, whatever the command; the
    commitments stating one aren't recorded (`held_back`). On commit the
    scene's rows in that file are replaced by this run's inherited
    findings. A contradiction in the brief's own words is a
    `plan_conflict` (`_classify`).

    On commit (Phase 4, `docs/plans/2026-10-31-phase4-safe-revision-design.md`):
    a new commitment stating the same fact as an earlier one of the scene
    (`ledger.fact_key`) keeps its id, and a later scene's end of it, so
    links to it hold. The earlier commitments with no such match, and the
    earlier states whose end in this scene came or went, are `changed`;
    the later scenes whose facts depend on them (`ledger.dependents`) and
    have prose are listed in `working/gate-pending.csv` as `recheck`
    (`recheck_pending` re-gates them). A fact new to the scene doesn't list
    anything: its own check already reads it against the later scenes.

    Raises:
        GateError: a step couldn't finish (extraction or the check failed,
            the scene has no prose, or the ledger changed on disk
            while the gate ran); nothing was written.
        ValueError: `command` isn't one of `GATE_COMMANDS`.
    """
    from storyforge.common import select_model
    from storyforge.extract import COMMITMENT_PROBLEMS
    if command not in GATE_COMMANDS:
        raise ValueError(f'command must be one of {", ".join(GATE_COMMANDS)}, not {command!r}')
    if prose is None:
        path = os.path.join(project_dir, 'scenes', f'{scene_id}.md')
        try:
            with open(path, encoding='utf-8') as f:
                prose = f.read()
        except OSError as e:
            raise GateError(f'{scene_id}: no prose to gate ({e})') from e
    if not prose.strip():
        raise GateError(f'{scene_id}: no prose to gate (the scene is empty)')
    if prose.lstrip().startswith('---\n'):
        raise GateError(f'{scene_id}: the scene starts with frontmatter; scene files are '
                        f'pure prose (`storyforge cleanup` strips it)')
    try:
        rows = ledger.load(project_dir)
        order = ledger.scene_order(project_dir)
        # read before the model calls: a commit needs both
        names, name_notes = ledger.subject_names(project_dir)
        revised_rejection = rejected_ids(pending(project_dir).get(scene_id))
        already_reported = reported(project_dir).get(scene_id, [])
        briefs_name = audit.brief_fact_ids(project_dir)
    except (ledger.LedgerError, ValueError, OSError, UnicodeDecodeError) as e:
        raise GateError(f'{scene_id}: {e}') from e
    loaded = copy.deepcopy(rows)
    if scene_id not in order:
        raise GateError(f'{scene_id} is not a scene in reference/scenes.csv')

    # The scene's earlier commitments (a redraft's) aren't offered back to it
    # and are replaced on commit; what leans on them is re-checked (Phase 4)
    # (binding ones: a rejected commitment stays, the record of the
    # author's decision, and prose restating it is a problem below)
    old_rows = [copy.deepcopy(r) for r in rows if ledger.is_commitment(r)
                and r.get('status') == 'binding'
                and (r.get('scene_id') or '').strip() == scene_id]
    rejected_here = {ledger.fact_key(r): r['id'] for r in rows
                     if r.get('status') == 'rejected'
                     and (r.get('scene_id') or '').strip() == scene_id}
    # #735: the facts an earlier provisional commit recorded as disputed are
    # replaced too: this version's own reading holds back, disputes or
    # commits them afresh. Not in force, so nothing changed by their going
    # (#735's review CR-3: every `pending` commitment of the scene, so a
    # disputed row whose stamp was edited away can't be left behind; a
    # superseded or rejected one stays, the record of a decision)
    held_rows = [copy.deepcopy(r) for r in rows if ledger.is_commitment(r)
                 and r.get('status') == 'pending'
                 and (r.get('scene_id') or '').strip() == scene_id]
    # #749: the claims in speech an earlier version recorded are replaced
    # too; never in force, so nothing changes by their going
    claim_rows = [copy.deepcopy(r) for r in rows if ledger.is_commitment(r)
                  and r.get('status') == ledger.CLAIM
                  and (r.get('scene_id') or '').strip() == scene_id]
    old = ({r['id'] for r in old_rows} | {r['id'] for r in held_rows}
           | {r['id'] for r in claim_rows})
    ended_before = ledger.ended_by(rows, scene_id)
    rows = [r for r in rows if r['id'] not in old]
    # ... and the ends the earlier version set: this version's extraction
    # sets its own
    for r in rows:
        if ledger.is_commitment(r) and (r.get('resolves') or '').strip() == scene_id:
            r['resolves'] = ''

    result = GateResult(scene_id, problems={k: [] for k in COMMITMENT_PROBLEMS + ('rejected',)})
    method = GATE_CHECK_METHOD
    if method not in CHECK_METHODS:
        raise GateError(f'GATE_CHECK_METHOD is {method!r}, not one of '
                        f'{", ".join(CHECK_METHODS)}')
    if method in ('questions', 'tandem') and not GATE_CONTINUITY:
        raise GateError(f'{scene_id}: the question layer asks about who is in the scene, '
                        f'from its typed state, so it needs the continuity checks '
                        f'(GATE_CONTINUITY)')
    tandem = method == 'tandem'
    # #738: a tandem run handed an earlier open reading makes none
    carry_open = tandem and open_from is not None and open_from.open_findings is not None
    read_open = method == 'open' or (tandem and not carry_open)
    ask = method in ('questions', 'tandem')
    skip, why_not = (blocking_read_before(project_dir, scene_id, prose)
                     if GATE_BLOCKING and command == 'recheck' else (False, ''))
    what = 'stage sheet' if GATE_BLOCKING_METHOD == 'stage-sheet' else 'blocking read'
    read_blocking = GATE_BLOCKING and not skip

    # Extraction (and its persistence check), the blocking read and the
    # typed state read the prose independently: their model calls run at
    # once (`runner.together`; one after the other, they were most of a
    # gate run's time: iliad-adult, 2026-11-17). Each writes only its own
    # part of `result`; what they find is merged below in the order the
    # steps ran one after the other, so a finding is kept or left out as
    # it was. The question layer (or the open checker) needs extraction's
    # disputes and the typed state's cast, so it comes after
    read: list = []
    carried, refused = _carry_of(carry)

    def extract():
        return _extract(project_dir, scene_id, prose, rows, order, introduced_by or command,
                        extract_model or select_model('evaluation'), log_dir,
                        result.problems, result.dropped,
                        reserved=_reserved_ids(old, loaded, briefs_name), ends=result.ends,
                        carry=carried, refused=refused, read_out=read, pinned=pinned)
    calls = [extract]
    if read_blocking:
        calls.append(lambda: _read_blocking(project_dir, scene_id, prose, check_model, log_dir,
                                            result))
    if GATE_CONTINUITY:
        # its own copy: extraction reads `rows` while this one does
        state_rows = copy.deepcopy(rows)
        calls.append(lambda: _read_continuity(project_dir, scene_id, prose, state_rows,
                                              log_dir))
    from storyforge.runner import together
    got = together(*calls)
    extracted = got.pop(0)
    # #749: a claim in speech is committed as what was said, apart from the
    # facts the run checks and commits as binding
    result.proposed = [r for r in extracted if r.get('status') != ledger.CLAIM]
    result.claims = [r for r in extracted if r.get('status') == ledger.CLAIM]
    result._extracted, result.extract_note = read[0]
    if result.extract_note:
        from storyforge.common import log
        log(f'  {scene_id}: {result.extract_note}')
    blocked = got.pop(0) if read_blocking else None
    state = got.pop(0) if GATE_CONTINUITY else None
    # A fact the author rejected may not come back as binding
    for r in result.proposed:
        rid = rejected_here.get(ledger.fact_key(r))
        if rid:
            result.problems['rejected'].append(
                f'{scene_id}: "{r.get("quote") or r.get("statement")}" restates {rid}, '
                f'which the author rejected')
    result.halts = _mark_planned(project_dir, scene_id,
                                 audit.halting_conditions(result.proposed, rows),
                                 result.proposed, rows)
    disputes = _disputes(result, rows)
    endings = _endings(result, rows)
    if not read_open:
        # filled after the typed state is read (`_ask_questions`)
        result.check = CheckResult(scene_id)
        if carry_open:
            # where the open reading would have put its findings: before
            # the shared layers', so one slip is not two (#738's review CR-4)
            _carry_open(scene_id, prose, open_from, disputes, log_dir, result,
                        endings=endings)
    else:
        try:
            result.check = check_scene(project_dir, scene_id, prose=prose, model=check_model,
                                       log_file=os.path.join(log_dir,
                                                             f'gate-check-{scene_id}.json'),
                                       rows=rows, disputes=disputes, readings=GATE_READINGS,
                                       endings=endings)
        except CheckError as e:
            error = GateError(str(e))
            error.run = getattr(e, 'run', None)
            raise error from e
        if tandem:
            for f in result.check.findings + result.check.unverified:
                f.checker = OPEN
            result.open_findings = result.check.findings + result.check.unverified
            result.open_prose = prose
            result.open_rulings = OpenRulings.of(result.check, disputes, endings)
            result.check_notes.append(
                f'first run: the open checker ({GATE_READINGS} reading(s)) and the questions '
                f'both read it')
    if skip:
        # #631: a re-check runs because an earlier scene changed; the
        # blocking check takes the scene alone, so on the gated prose it can
        # only read the same words again (and word them otherwise)
        result.blocking_method = GATE_BLOCKING_METHOD
        result.blocking_skipped = True
        result.blocking_note = (f'{what} skipped: the prose is unchanged since its last gate, '
                                + ('which read its blocking' if what == 'blocking read'
                                   else 'which checked it with the stage sheet'))
    elif GATE_BLOCKING:
        if command == 'recheck':
            result.blocking_note = f'{what} run: {why_not}'
        # The scene against itself (#626): the checker reads it against the
        # book; this reads its blocking alone. Its findings join the check's,
        # so they are sorted, reported, fixed and accepted the same way
        result.check.findings.extend(blocked.findings)
        result.check.unverified.extend(blocked.unverified)
        result.blocking_method = GATE_BLOCKING_METHOD
    if result.blocking_note:
        from storyforge.common import log
        log(f'  {scene_id}: {result.blocking_note}')
    if GATE_CONTINUITY:
        records = _merge_continuity(scene_id, state, result)
        if ask:
            _ask_questions(project_dir, scene_id, prose, rows, records, disputes, log_dir,
                           result, endings=endings,
                           tandem=(READ if read_open else CARRIED) if tandem else '')
    if result.check_notes:
        from storyforge.common import log
        log(f'  {scene_id}: tandem: ' + '; '.join(result.check_notes))
    # #642: a `must` line's words, checked by code
    result.check.findings.extend(_verbatim_findings(project_dir, scene_id, prose, result.check,
                                                    short_lines=result.short_must))
    if standing is not None:   # after the code's own, which it makes again
        _carry_standing(result.check, standing, disputes)
    # a fix's re-check carrying a reading that held slips back rebuilds
    # them from its replies: the retry has been had, so they stay held
    if hold_slips or (carry is not None and carry.slips_held):
        _hold_slips(result)
    _classify(result, project_dir, before, already_reported, prose=prose, rows=rows)
    result._ctx = _CommitContext(rows, loaded, old_rows, ended_before, revised_rejection,
                                 names, name_notes, order, prose, command, held_rows,
                                 claim_rows)
    _apply_source(result, project_dir, scene_id, prose, order, log_dir,
                  extract_model or select_model('evaluation'), old_rows)
    _note_advisory(project_dir, scene_id, command, result, prose=prose)
    if not result.passed:
        _note_blocked(project_dir, scene_id, command, result)
        return result
    _commit(project_dir, result)
    return result


#: #736's review CR-1: the continuity checks whose findings are about a
#: state (`continuity.CODES`: PHY, KNO): a fix for one writes a change of state
_STATE_CHECKS = ('life', 'possession', 'injury', 'knowledge')


def _carry_of(run: 'GateResult | None') -> tuple['_Extracted | None', str]:
    """#736: what `run` (the run of the prose before a fix) read, for the
    re-check to carry, with the state codes among the findings sent to the
    fix (`_Extracted.state_codes`), and ''; or None and why not (#736's
    review SF-1: said in the log): it didn't reach extraction, or
    extraction problems stopped it (`unresolved`: a misquote, a link to
    nothing, a rejected fact), which its re-check reads again, as before
    (#734: the fix's re-check re-reads a slip's facts). (None, '') with no
    `run`."""
    from dataclasses import replace

    from storyforge.continuity import CODES
    if run is None:
        return None, ''
    if run._extracted is None:
        return None, 'the run before the fix has no extraction to carry'
    if run.unresolved:
        return None, (f'the run before the fix had extraction problems '
                      f'({_one_line("; ".join(run.unresolved))[:120]})')
    states = {CODES[k] for k in _STATE_CHECKS} & {f.code for f in run.fixable + run.unverified}
    return replace(run._extracted, state_codes=frozenset(states)), ''


def _reserved_ids(old: Set[str], loaded: list[dict[str, str]],
                  briefs_name: Set[str]) -> set[str]:
    """The ids no new commitment of the scene may take though the ledger the
    scene is read against hasn't got them (#599, and its review TD-1/SF-2):
    the scene's earlier commitments (`old`, an id not carried is never
    reused), and every id a link names, in the ledger (`ledger.linked_ids`,
    `loaded`) or a brief (`briefs_name`), there or not: an id dropped by an
    earlier commit and minted again would put that link on a different
    fact."""
    return set(old) | ledger.linked_ids(loaded) | set(briefs_name)


@dataclass
class _CommitContext:
    """What `_gate_scene` read before its model calls, for `_commit`."""
    rows: list[dict[str, str]]          # the ledger without the scene's old commitments
    loaded: list[dict[str, str]]        # the ledger as loaded
    old_rows: list[dict[str, str]]
    ended_before: set[str]
    revised_rejection: list[str]
    names: dict[str, set[str]]
    name_notes: list[str]
    order: dict[str, int]
    prose: str
    command: str
    #: the scene's commitments an earlier provisional commit recorded as
    #: disputed (#735, `is_held`): replaced on commit, their ids carried
    held: list[dict[str, str]] = field(default_factory=list)
    #: #749: the scene's claims in speech an earlier commit recorded:
    #: replaced on commit, their ids carried to the same claim read again
    claims: list[dict[str, str]] = field(default_factory=list)


#: A pending row's command for a scene `write --keep-going` committed
#: without a pass (`commit_provisional`): its facts are in the ledger, those
#: stating what stopped it as disputed (#735, not in force), and its
#: findings are the author's
PROVISIONAL = 'provisional'

#: The `reviewed` stamp of a commitment a provisional commit recorded as
#: disputed (#735): `held:` and the key of the finding it states
#: (`finding_key`). With status `pending` it is in the ledger but not in
#: force: every reader of the facts in force reads `binding` rows only
HELD = 'held:'


def is_held(row: dict[str, str]) -> bool:
    """Whether `row` is a commitment recorded as disputed (#735)."""
    return (row.get('status') == 'pending' and ledger.is_commitment(row)
            and (row.get('reviewed') or '').startswith(HELD))


#: The part of a `HELD` stamp naming the earlier states the disputed fact
#: ends (#735's review CR-1/CR-2): applied when it comes into force
_HELD_ENDS = ' ends:'


def held_stamp(keys: list[str], ends: list[str] = ()) -> str:
    """A disputed fact's `reviewed`: `held:` and the keys of the findings it
    states (`;`-joined), then ` ends:` and the earlier states it ends."""
    return HELD + ';'.join(keys) + (_HELD_ENDS + ';'.join(ends) if ends else '')


def held_parts(reviewed: str) -> tuple[list[str], list[str]]:
    """(finding keys, ended state ids) of a `held_stamp`."""
    if not (reviewed or '').startswith(HELD):
        return [], []
    keys, _, ends = reviewed[len(HELD):].partition(_HELD_ENDS)
    return ([k for k in keys.split(';') if k], [e for e in ends.split(';') if e])


def finding_row_key(row: dict[str, str]) -> str:
    """The key of a finding as `BLOCKED_PATH` records it (`_finding_rows`):
    its source and its quote's words, as `_same` matches two."""
    return _paragraph_key(f"{row.get('source', '')} {_words(row.get('quote', ''))}".split())


def finding_key(f: Finding) -> str:
    """`finding_row_key` of `f` as `record_blocked` would record it."""
    return finding_row_key(_finding_rows('', '', [f])[0])


def can_commit_provisionally(result: GateResult) -> str:
    """Why `result` can't be committed provisionally ('' when it can): only
    the check's findings stopped it (contradictions, broken `must` beats and
    registry facts set up here, plan conflicts, unverified ones). A halt (a
    fixed fact changed) or an extraction problem would commit a wrong row.
    An unruled dispute doesn't stop the scene (advisory), so it never comes
    to this."""
    if result.passed or result.committed:
        return 'it was committed'
    if getattr(result, '_ctx', None) is None:
        return 'the gate run did not finish'
    if any(h.planned for h in result.halts):
        return ('it changes a fixed fact its plan calls for (unfix the fact: '
                '`storyforge check --unfix ' + ','.join(_planned_fixed(result)) + '`)')
    if result.halts:
        return 'it changes a fixed fact (a halt)'
    if result.unresolved:
        return 'extraction left problems a commit would write'
    return ''


def _planned_fixed(result: GateResult) -> list[str]:
    """The fixed facts `result`'s plan-called halts change (#788), once each."""
    return list(dict.fromkeys(h.fixed_id for h in result.halts if h.planned))


def commit_provisional(project_dir: str, result: GateResult, reason: str) -> None:
    """Commit a scene that didn't pass, for `write --keep-going` (#556,
    G-028/B-028/B-030: one stop ended an unattended draft): its commitments
    replace its earlier ones as on a pass, each one stating a blocking
    finding (`_hold_back`) recorded as disputed, not in force (#735:
    `is_held`, brought into force by `accept_blocked`), and what they
    changed is listed for a re-check; the scene is listed `PROVISIONAL` in
    `PENDING_PATH` with
    `reason`, and its verified contradictions stay in `BLOCKED_PATH` for
    `storyforge check --accept`. A later scene is then drafted from
    everything the scene got right. Sets `.committed` and `.provisional`.

    Raises:
        GateError: `can_commit_provisionally` says no, or the ledger changed
            since the gate run (nothing written).
    """
    why = can_commit_provisionally(result)
    if why:
        raise GateError(f'{result.scene_id}: not committed provisionally: {why}')
    _commit(project_dir, result, holding=result.findings + result.unverified,
            pending_reason=reason)
    result.provisional = True


def _commit(project_dir: str, result: GateResult, holding: list[Finding] | None = None,
            pending_reason: str = '') -> None:
    """Write `result`'s commitments (its gate run's `_ctx`): on a pass, or
    provisionally (`holding`: the findings it was committed in spite of,
    whose commitments are held back, and `pending_reason` for its
    `PROVISIONAL` row)."""
    ctx = result._ctx
    scene_id, command, prose = result.scene_id, ctx.command, ctx.prose
    rows, old_rows, order = ctx.rows, ctx.old_rows, ctx.order
    ended_before, revised_rejection = ctx.ended_before, ctx.revised_rejection
    names, name_notes = ctx.names, ctx.name_notes
    # The model calls take minutes: a ledger changed meanwhile would be
    # overwritten, and its change logged under this command
    try:
        if ledger.load(project_dir) != ctx.loaded:
            raise GateError(f'{scene_id}: reference/commitments.csv changed while the '
                            f'scene was being gated; nothing written, gate it again')
    except ledger.LedgerError as e:
        raise GateError(f'{scene_id}: {e}') from e
    # #599's review (TD-3): a refused write leaves the result and the
    # context as they were, never half-committed
    saved = copy.deepcopy({k: v for k, v in vars(result).items() if k != '_ctx'})
    saved_rows = copy.deepcopy(rows)
    try:
        fixed_toward_source = _write_commit(project_dir, result, holding, rows, old_rows,
                                            order, ended_before, revised_rejection, names,
                                            name_notes, prose, command, scene_id,
                                            loaded=ctx.loaded, held=ctx.held,
                                            claims=ctx.claims)
    except BaseException:
        vars(result).update(saved)
        rows[:] = saved_rows
        raise
    result.committed = True
    _after_commit(project_dir, result, holding, pending_reason, prose, command, scene_id,
                  fixed_toward_source)


def _write_commit(project_dir, result, holding, rows, old_rows, order, ended_before,
                  revised_rejection, names, name_notes, prose, command, scene_id,
                  loaded=(), held=(), claims=()) -> bool:
    """`_commit`'s changes to `result` and `rows`, ending in the ledger
    write; returns whether the scene was fixed toward its source. `held`:
    the scene's disputed commitments before (#735), whose ids carry;
    `claims`: its claims in speech before (#749), whose ids carry to the
    same claim read again."""
    _source_supersede(result, rows)
    fixed_toward_source = _keep_superseded(project_dir, result, rows, prose)
    # #558's second review: the kept facts go through the hold-back too,
    # which keeps them and reports them (#632)
    _keep_steady(project_dir, result, old_rows, prose)
    _hold_back(result, holding, prose=prose if holding else '', rows=rows)
    _apply_ends(project_dir, result, rows, old_rows, prose, loaded, held=held)
    # #735: a disputed fact keeps its id across commits, and an earlier
    # one's id goes to the same fact read again, disputed or not
    _carry_ids(result.proposed + result.disputed_rows, list(old_rows) + list(held),
               result.steady)
    if result.claims:
        _carry_ids(result.claims, list(claims), [])
    new = rows + result.proposed + result.disputed_rows + result.claims
    for rid, quote in result.check.kept:
        if ledger.fill_quote(new, rid, quote):
            result.quotes_filled.append(rid)
    # the old side only: a fact new to the scene lists nothing
    new_keys = {ledger._fact_key(r) for r in result.proposed}
    result.changed = [r['id'] for r in old_rows if ledger._fact_key(r) not in new_keys]
    # #735's review SF-1: a disputed fact coming into force is a change: the
    # later scenes were gated while it was held. One dropped while held
    # changes nothing in force
    held_keys = {ledger.fact_key(r) for r in held}
    result.changed += [r['id'] for r in result.proposed
                       if ledger.fact_key(r) in held_keys and r['id'] not in result.changed]
    held_ends = {e for r in held for e in held_parts(r.get('reviewed', ''))[1]}
    _keep_steady_ends(project_dir, result, new, ended_before, loaded, prose,
                      claimed=held_ends)
    result.changed += sorted(ended_before ^ ledger.ended_by(new, scene_id))
    # #734's review CR-3: a state the plan sets up here that this version
    # ends, or no longer ends, changes what the later scenes have in force
    here_ids = _here_registry_ids(rows, scene_id)
    result.changed += [i for i in sorted(_ended_here(old_rows, here_ids)
                                         ^ _ended_here(result.proposed, here_ids))
                       if i not in result.changed]
    result.changed += [i for i in revised_rejection if i not in result.changed]
    if result.changed:
        # #632: the narrower rule (a compatible type, mentions only in
        # knowledge and relationship facts) for what the prose changed; a
        # rejected fact keeps the wide one, which `audit --mark rejected`
        # told the author it would list (`cmd_audit._reject_recheck`)
        rejected = [i for i in result.changed if i in revised_rejection]
        found = ledger.dependents(old_rows + new,
                                  [i for i in result.changed if i not in rejected],
                                  order, names=names, narrow=True)
        if rejected:
            wide = ledger.dependents(old_rows + new, rejected, order, names=names)
            found.scenes = sorted(set(found.scenes) | set(wide.scenes), key=order.get)
            found.unrelated.update(wide.unrelated)
            found.why = {**wide.why, **found.why}
        result.unrelated = found.unrelated
        result.name_notes = name_notes
        # a rejected fact's re-check also reaches the scenes whose brief
        # names it, as `audit --mark rejected` tells the author it will
        briefs = audit.leaning_scenes(project_dir, revised_rejection) if revised_rejection else {}
        named = {b for v in briefs.values() for b in v}
        briefs_named = set(named)
        # #621: a state whose end moved here from a later scene: that scene
        # ended it, and is re-checked (the moved row no longer names it)
        newly_ended = ledger.ended_by(new, scene_id) - ended_before
        named |= {end for r in loaded if r['id'] in newly_ended
                  for end in [(r.get('resolves') or '').strip()]
                  if end and end != scene_id}
        # only what follows the scene can depend on how the scene changed
        later = sorted({s for s in set(found.scenes) | named
                        if s in order and order[s] > order[scene_id]}, key=order.get)
        gone = _gone_scenes(project_dir)
        result.recheck = [s for s in later if s not in gone and _has_prose(project_dir, s)]
        result.recheck_why = {s: found.why.get(s) or (
            'its brief names a rejected fact' if s in briefs_named else
            'an end moved here from it') for s in result.recheck}
        result.not_rechecked = [f'{s} ({"cut or merged" if s in gone else "no prose yet"})'
                                for s in later if s not in result.recheck]
        result.not_rechecked += [f'{s} (its brief names a rejected fact, but it is not in '
                                 f'scenes.csv)' for s in sorted(named - set(order))]
        removed = set(result.changed) - {r['id'] for r in result.proposed}
        result.dangling = [f'{r["id"]} → {ref}' for r in rows if not ledger.is_commitment(r)
                           for col in ('supersedes', 'depends_on')
                           for ref in ledger._split(r.get(col, '')) if ref in removed]
    # #599: never a ledger the next command can't load; a cell that would
    # break its row is refused the same way (#599's review, SF-3: it was
    # uncaught, and stopped `check --pending --keep-going`)
    try:
        ledger.save(project_dir, new, command=command)
    except (ledger.LedgerError, ValueError) as e:
        raise LedgerWriteRefused(f'{scene_id}: ledger write refused: {e}') from e
    return fixed_toward_source


def _after_commit(project_dir, result, holding, pending_reason, prose, command, scene_id,
                  fixed_toward_source) -> None:
    """What follows a written commit: the prose recorded, the source-fix,
    reported, blocked and pending lists updated (a failure is a WARNING:
    the ledger is written)."""
    note = record_prose(project_dir, scene_id, prose, blocking=result.blocking_method)
    if note:
        result.prose_notes.append(f'{scene_id}: {note}')
    if fixed_toward_source:
        try:
            clear_source_fix(project_dir, scene_id)
        except GateError as e:
            result.source_notes.append(f'{SOURCE_FIX_PATH} could not be updated ({e}); '
                                       f'remove {scene_id}\'s row by hand')
    try:
        record_reported(project_dir, scene_id, command, result.inherited, prose=prose,
                        keep_blocking=result.blocking_skipped)
        if holding is None:
            record_blocked(project_dir, scene_id, command, [])
    except GateError as e:   # the ledger is written; the findings were logged
        from storyforge.common import log
        log(f'WARNING: {scene_id} passed, but {REPORTED_PATH} could not be updated: {e}. '
            f'Its contradictions already in the scene are only in this log.')
    if holding is not None and result.disputed:
        # #735's review SF-5: the author sees what is waiting on them
        pending_reason += (f' [{len(result.disputed)} fact(s) recorded as disputed: '
                           + '; '.join(_one_line(st)[:80] for st, _ in result.disputed[:3])
                           + ('; ...' if len(result.disputed) > 3 else '') + ']')
    try:
        if holding is not None:
            mark_pending(project_dir, scene_id, PROVISIONAL, pending_reason)
        else:
            clear_pending(project_dir, scene_id)
        waiting = pending(project_dir)
        for sid in result.recheck:
            if sid not in waiting:   # one waiting for another reason stays as it is
                why = result.recheck_why.get(sid)
                mark_pending(project_dir, sid, RECHECK,
                             f're-check: {scene_id} changed {len(result.changed)} fact(s) '
                             f'its facts depend on' + (f' ({why})' if why else ''))
        for f, why in result.source_backed:
            mark_source_fix(project_dir, f.established_scene,
                            f'{scene_id} tells it the source\'s way and this scene does not: '
                            f'"{_one_line(f.established_quote)[:120]}" ({_one_line(why)[:160]})')
        if result.source_departs:
            mark_source_fix(project_dir, scene_id,
                            f'the source contradicts {len(result.source_departs)} fact(s) read '
                            f'from it (recorded as the book has them): '
                            + '; '.join(_one_line(st)[:100] for st, _ in result.source_departs[:3]),
                            prose=prose, refresh=True)
    except GateError as e:   # the ledger is written; say why the list wasn't updated
        from storyforge.common import log
        log(f'WARNING: {scene_id} passed, but {PENDING_PATH} could not be updated: {e}. '
            f'Fix it by hand: remove {scene_id}\'s row'
            + (f' and add {", ".join(result.recheck)} for a re-check' if result.recheck else '')
            + '.')


def _finding_fact_ids(f: Finding, rows: list[dict[str, str]]) -> list[str]:
    """The binding commitments `f` says the scene contradicts: the one its
    `fact_id` names, or those of its established scene whose quote holds
    the established words (or is held by them)."""
    out = []
    for r in rows:
        if not ledger.is_commitment(r) or r.get('status') != 'binding':
            continue
        if f.fact_id and r.get('id') == f.fact_id:
            out.append(r['id'])
        elif (f.established_scene and (r.get('scene_id') or '').strip() == f.established_scene
              and f.established_quote and r.get('quote')
              and (_found_in(r['quote'], f.established_quote)
                   or _found_in(f.established_quote, r['quote']))):
            out.append(r['id'])
    return out


def _source_supersede(result: GateResult, rows: list[dict[str, str]]) -> None:
    """For each contradiction the source backs this scene on (#557's
    review): the earlier scene's commitments stating it become
    `superseded` (no longer binding), so later scenes are drafted and
    checked against the source's telling, which this scene's facts then
    commit. One whose earlier fact can't be found is held back instead
    (`source_unmatched`, `_hold_back`). In place on `rows`."""
    result.source_superseded, result.source_unmatched = [], []
    for f, _ in result.source_backed:
        ids = _finding_fact_ids(f, rows)
        if not ids:
            result.source_unmatched.append(f)
            continue
        for r in rows:
            if r.get('id') in ids:
                r['status'] = 'superseded'
        result.source_superseded += [i for i in ids if i not in result.source_superseded]


#: The scenes listed for the author to fix toward the source (#557), apart
#: from working/gate-pending.csv so a re-check's pass there never clears
#: one (#557's second review): `scene_id|prose|reason`, `prose` the sha1 of
#: the scene's prose when listed. Only a commit of that scene with other
#: prose takes a row off (`_keep_superseded`, `clear_source_fix`)
SOURCE_FIX_PATH = 'working/gate-source-fix.csv'
_SOURCE_FIX_COLUMNS = ['scene_id', 'prose', 'reason']


def _prose_sha(text: str) -> str:
    import hashlib
    return hashlib.sha1(text.encode('utf-8')).hexdigest()


def _scene_sha(project_dir: str, scene_id: str) -> str:
    try:
        with open(os.path.join(project_dir, 'scenes', f'{scene_id}.md'), encoding='utf-8') as f:
            return _prose_sha(f.read())
    except (OSError, UnicodeDecodeError):
        return 'none'


def source_fixes(project_dir: str) -> dict[str, dict[str, str]]:
    """Scene id → its `SOURCE_FIX_PATH` row.

    Raises:
        GateError: the file is malformed or unreadable."""
    path = os.path.join(project_dir, SOURCE_FIX_PATH)
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding='utf-8') as f:
            lines = [line.rstrip('\n') for line in f if line.strip()]
    except (OSError, UnicodeDecodeError) as e:
        raise GateError(f'{SOURCE_FIX_PATH}: {e}') from e
    if not lines or lines[0].split('|') != _SOURCE_FIX_COLUMNS:
        raise GateError(f'{SOURCE_FIX_PATH}: the header must be {"|".join(_SOURCE_FIX_COLUMNS)}')
    out = {}
    for line in lines[1:]:
        cells = line.split('|', 2)
        if len(cells) != 3:
            raise GateError(f'{SOURCE_FIX_PATH}: a bad row: {line[:80]!r}')
        out[cells[0]] = dict(zip(_SOURCE_FIX_COLUMNS, cells))
    return out


def _write_source_fixes(project_dir: str, rows: dict[str, dict[str, str]]) -> None:
    path = os.path.join(project_dir, SOURCE_FIX_PATH)
    if not rows:
        if os.path.isfile(path):
            os.remove(path)
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='') as f:
        f.write('|'.join(_SOURCE_FIX_COLUMNS) + '\n')
        for sid in sorted(rows):
            f.write('|'.join(rows[sid][c] for c in _SOURCE_FIX_COLUMNS) + '\n')


def mark_source_fix(project_dir: str, scene_id: str, why: str, prose: str | None = None,
                    refresh: bool = False) -> None:
    """List `scene_id` for the author to fix toward the source (#557), in
    `SOURCE_FIX_PATH`, with the prose it has now (`prose`, else the scene
    file): the row stays until a commit of the scene with other prose. A
    scene listed already gets `why` added. `refresh`: a row already giving
    `why` takes the prose it has now (#742's review, SF-1: a departure the
    edited prose still has, so `check --pending` waits on the author again)."""
    from storyforge.common import csv_safe
    rows = source_fixes(project_dir)
    sha = _prose_sha(prose) if prose is not None else _scene_sha(project_dir, scene_id)
    why = csv_safe(_one_line(why))
    old = rows.get(scene_id)
    if old and why in old['reason']:
        if refresh and old['prose'] != sha:
            rows[scene_id] = dict(old, prose=sha)
            _write_source_fixes(project_dir, rows)
        return
    reason = f"{old['reason']} / {why}" if old else why
    rows[scene_id] = {'scene_id': scene_id, 'prose': sha, 'reason': reason}
    _write_source_fixes(project_dir, rows)


#: #742: the source's own passages behind blocking findings the source
#: check found the source narrates the same way (`GateResult.source_has_it`),
#: for the author: `scene_id|prose|finding|source_quote|why`, `prose` the
#: sha1 of the prose ruled on. The finding still blocks and is fixed; the
#: row is the author's record that the original has it (whether to keep it,
#: with the license on the page, is theirs). One row a scene, finding and
#: source passage; the gate never takes a row off
SOURCE_NOTES_PATH = 'working/gate-source-notes.csv'
_SOURCE_NOTES_COLUMNS = ['scene_id', 'prose', 'finding', 'source_quote', 'why']


def source_notes(project_dir: str) -> list[dict[str, str]]:
    """The rows of `SOURCE_NOTES_PATH`, in file order.

    Raises:
        GateError: the file is malformed or unreadable."""
    path = os.path.join(project_dir, SOURCE_NOTES_PATH)
    if not os.path.isfile(path):
        return []
    try:
        with open(path, encoding='utf-8') as f:
            lines = [line.rstrip('\r\n') for line in f if line.strip()]
    except (OSError, UnicodeDecodeError) as e:
        raise GateError(f'{SOURCE_NOTES_PATH}: {e}') from e
    if not lines or lines[0].split('|') != _SOURCE_NOTES_COLUMNS:
        raise GateError(f'{SOURCE_NOTES_PATH}: the header must be '
                        f'{"|".join(_SOURCE_NOTES_COLUMNS)}')
    out = []
    for line in lines[1:]:
        cells = line.split('|')
        if len(cells) != len(_SOURCE_NOTES_COLUMNS):
            raise GateError(f'{SOURCE_NOTES_PATH}: a bad row: {line[:80]!r}')
        out.append(dict(zip(_SOURCE_NOTES_COLUMNS, cells)))
    return out


def note_source_has_it(project_dir: str, scene_id: str, prose: str,
                       found: list[tuple['Finding | str', str, str]]) -> None:
    """Add a `SOURCE_NOTES_PATH` row for each (finding, source quote, why)
    of `scene_id` whose source passage the scene has no row for yet. A
    finding may be words of its own (#749's review CR-2: a claim in speech
    the source tells otherwise).

    Raises:
        GateError: the file is malformed or unreadable."""
    from storyforge.common import csv_safe
    from storyforge.quotes import normalize
    rows = source_notes(project_dir)
    have = {(r['scene_id'], normalize(r['finding']), normalize(r['source_quote']))
            for r in rows}
    sha = _prose_sha(prose)
    added = False
    for f, quote, why in found:
        quote = csv_safe(_one_line(quote))
        finding = csv_safe(_one_line(f if isinstance(f, str) else f.message()))
        key = (scene_id, normalize(finding), normalize(quote))
        if key in have:
            continue
        have.add(key)
        rows.append({'scene_id': scene_id, 'prose': sha, 'finding': finding,
                     'source_quote': quote, 'why': csv_safe(_one_line(why))})
        added = True
    if not added:
        return
    path = os.path.join(project_dir, SOURCE_NOTES_PATH)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='') as f:
        f.write('|'.join(_SOURCE_NOTES_COLUMNS) + '\n')
        for r in rows:
            f.write('|'.join(r[c] for c in _SOURCE_NOTES_COLUMNS) + '\n')


def clear_source_fix(project_dir: str, scene_id: str) -> None:
    rows = source_fixes(project_dir)
    if rows.pop(scene_id, None) is not None:
        _write_source_fixes(project_dir, rows)


def source_fix_waits(project_dir: str, scene_id: str, prose: str | None = None) -> bool:
    """Whether `scene_id` is listed to fix toward the source and its prose
    (`prose`, else the scene file) hasn't changed since: checking it again
    can't clear the row."""
    try:
        row = source_fixes(project_dir).get(scene_id)
    except GateError:
        return False
    if not row:
        return False
    sha = _prose_sha(prose) if prose is not None else _scene_sha(project_dir, scene_id)
    return row['prose'] == sha


def _keep_superseded(project_dir: str, result: GateResult, rows: list[dict[str, str]],
                     prose: str) -> bool:
    """#557's second and third reviews: a scene's `superseded` commitments
    (the source ruled them wrong) are never bound again. A proposed row
    restating one is dropped: the same fact, a quote holding or held by its
    quote, or the same subject and a value it states (`_values`: "300
    people" from another sentence, filed under another type). One is
    retired (taken out of `rows`) only when the scene is listed to fix
    toward the source and its prose was fixed: the words its quote came
    from are gone from the prose, nothing proposed restates it, and the
    source check ruled on every new fact (a failed call, or one that gave
    no verdict, retires nothing: a one-word edit elsewhere or an added
    newline isn't a fix). Returns True when every one was retired, so the
    listing comes off after the commit."""
    mine = [r for r in rows if r.get('status') == 'superseded'
            and (r.get('scene_id') or '').strip() == result.scene_id
            and ledger.is_commitment(r)]
    try:
        listed = source_fixes(project_dir).get(result.scene_id)
    except GateError as e:
        result.source_notes.append(str(e))
        listed = None
    if not mine:
        # #742's review (SF-1): every fact was sent again (`_apply_source`)
        # and none departs from the source
        return (bool(listed) and listed['prose'] != _prose_sha(prose) and result.source_ruled
                and not result.source_departs)

    def subject(r: dict[str, str]) -> str:
        return (r.get('subject') or '').strip().casefold()

    def restates(p: dict[str, str], r: dict[str, str]) -> bool:
        q, o = _words(p.get('quote') or ''), _words(r.get('quote') or '')
        if ledger.fact_key(p) == ledger.fact_key(r):
            return True
        if _count(q) >= _MIN_QUOTE_WORDS and o.strip() and (q in o or o in q):
            return True
        values = _values(r.get('statement', ''))
        return bool(subject(r) and subject(p) == subject(r) and values
                    and values & _values(p.get('statement', '')))
    again = [p for p in result.proposed if any(restates(p, r) for r in mine)]
    if again:
        result.proposed = [p for p in result.proposed if p not in again]
        result.source_notes.append('not recorded, the source ruled them wrong (superseded): '
                                   + '; '.join(_one_line(p.get('statement', ''))[:100]
                                               for p in again))
    if not listed or listed['prose'] == _prose_sha(prose):
        return False
    if not result.source_ruled:
        result.source_notes.append('superseded rows kept and the source fix left open: the '
                                   'source check gave no ruling on this prose')
        return False
    fixed = [r for r in mine if not (r.get('quote') and _found_in(r['quote'], prose))
             and not any(restates(p, r) for p in again)]
    if fixed:
        gone = {r['id'] for r in fixed}
        rows[:] = [r for r in rows if r.get('id') not in gone]
        result.source_notes.append(f'retired, the prose fixed toward the source: '
                                   f'{", ".join(sorted(gone))}')
    return len(fixed) == len(mine) and not result.source_departs


#: The prose each committed scene's commitments were read from, as the git
#: blob of its text (#558): what `steady_facts` diffs a later version
#: against. Rows replaced on each commit
PROSE_PATH = 'working/gate-prose.csv'
#: `blocking`: how the gate run that committed the prose checked its
#: blocking, one of `BLOCKING_METHODS` (`read`, #631; `stage-sheet`, #647),
#: so a re-check of the same prose by the same method skips it; blank for a
#: scene gated before #626, or with the check off
_PROSE_COLUMNS = ['scene_id', 'blob', 'blocking']
#: the header before #631, still read (its rows had no blocking read)
_OLD_PROSE_COLUMNS = ['scene_id', 'blob']


def _git_out(project_dir: str, *args: str, data: bytes | None = None) -> bytes | None:
    import subprocess
    try:
        r = subprocess.run(['git', '-C', project_dir, *args], input=data,
                           capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


def _prose_table(project_dir: str) -> dict[str, dict[str, str]]:
    """Scene id → its `PROSE_PATH` row (`blob`, `blocking`). A file with the
    header from before #631 (no `blocking` column) reads as blank there."""
    path = os.path.join(project_dir, PROSE_PATH)
    if not os.path.isfile(path):
        return {}
    with open(path, encoding='utf-8') as f:
        lines = [line.rstrip('\n') for line in f if line.strip()]
    header = lines[0].split('|') if lines else []
    if header not in (_PROSE_COLUMNS, _OLD_PROSE_COLUMNS):
        raise ValueError(f'{PROSE_PATH}: the header must be {"|".join(_PROSE_COLUMNS)}')
    out = {}
    for line in lines[1:]:
        cells = line.split('|')
        if len(cells) < 2:
            continue
        out[cells[0]] = {'blob': cells[1],
                         'blocking': cells[2] if len(cells) > 2 else ''}
    return out


def _prose_rows(project_dir: str) -> dict[str, str]:
    """Scene id → the git blob of the prose its commitments were read from."""
    return {sid: row['blob'] for sid, row in _prose_table(project_dir).items()}


def gated_prose(project_dir: str, scene_id: str) -> tuple[str | None, str]:
    """The prose `scene_id`'s commitments were last read from (`PROSE_PATH`,
    read back from git), or None and why not."""
    try:
        blob = _prose_rows(project_dir).get(scene_id)
    except (OSError, UnicodeDecodeError, ValueError) as e:
        return None, f'{PROSE_PATH} can\'t be read ({e})'
    if not blob:
        earlier = _prose_from_history(project_dir, scene_id)
        if earlier is not None:
            return earlier, ''
        return None, f'{PROSE_PATH} doesn\'t record the prose its facts were read from'
    out = _git_out(project_dir, 'cat-file', 'blob', blob)
    if out is None:
        # #632: the committed prose at the scene's last gate commit, as for
        # a book gated before PROSE_PATH existed
        earlier = _prose_from_history(project_dir, scene_id)
        if earlier is not None:
            return earlier, ''
        return None, f'git has no blob {blob[:12]} (the prose its facts were read from)'
    return out.decode('utf-8', errors='replace'), ''


def blocking_read_before(project_dir: str, scene_id: str, prose: str,
                         method: str | None = None) -> tuple[bool, str]:
    """#631: whether `prose` is the prose `scene_id` was last committed with
    (`PROSE_PATH`: the same git blob) and that commit's gate run checked its
    blocking by `method` (default `GATE_BLOCKING_METHOD`; #647: a scene
    checked by the stage sheet still gets the read, and the other way
    round), and why not. The blocking check takes the scene alone, so on
    the same prose another one can only add noise (a new reading of the
    same words), never a finding a change elsewhere made."""
    method = method or GATE_BLOCKING_METHOD
    try:
        row = _prose_table(project_dir).get(scene_id)
    except (OSError, UnicodeDecodeError, ValueError) as e:
        return False, f'{PROSE_PATH} can\'t be read ({e})'
    if not row or not row['blob']:
        return False, f'{PROSE_PATH} records no gated prose for it'
    blob = _git_out(project_dir, 'hash-object', '--stdin', data=prose.encode('utf-8'))
    if blob is None:
        return False, 'git can\'t compare the prose with the gated one'
    if blob.decode().strip() != row['blob']:
        return False, 'its prose changed since its last gate'
    if not row['blocking']:
        return False, 'its last gate had no blocking read (gated before it existed)'
    if row['blocking'] != method:
        return False, f'its last gate checked its blocking by {row["blocking"]}, not {method}'
    return True, ''


#: How far back `_prose_from_history` looks through the ledger's commits.
_HISTORY_DEPTH = 300


def _scene_rows(text: str, scene_id: str) -> list[str] | None:
    """The ledger lines of `scene_id` in a ledger's text, sorted; None when
    the text has no scene_id column."""
    lines = text.splitlines()
    if not lines or 'scene_id' not in lines[0].split('|'):
        return None
    at = lines[0].split('|').index('scene_id')
    return sorted(line for line in lines[1:]
                  if (cells := line.split('|')) and len(cells) > at and cells[at] == scene_id)


def _prose_from_history(project_dir: str, scene_id: str) -> str | None:
    """The prose `scene_id`'s commitments were read from, for a book gated
    before `PROSE_PATH` existed (Beowulf B-033): the scene file as it stood at
    the latest commit that changed the scene's ledger rows. The gate commits
    a scene's facts with the prose it read; revise's commit of the prose
    alone, before its gate, doesn't touch the ledger and is passed over.
    None when the working ledger's rows for the scene differ from the last
    committed ones (a fact not yet committed: history can't say what it was
    read from), or git has nothing to say."""
    rel = f'reference/{ledger.LEDGER_FILE}'
    try:
        with open(os.path.join(project_dir, rel), encoding='utf-8') as f:
            current = _scene_rows(f.read(), scene_id)
    except (OSError, UnicodeDecodeError):
        return None
    if not current:
        return None
    log = _git_out(project_dir, 'log', '--format=%H', '-n', str(_HISTORY_DEPTH), '--', rel)
    shas = log.decode().split() if log else []

    def rows_at(sha: str) -> list[str] | None:
        out = _git_out(project_dir, 'show', f'{sha}:./{rel}')
        return _scene_rows(out.decode('utf-8', errors='replace'), scene_id) if out else []

    rows = rows_at(shas[0]) if shas else None
    if rows != current:
        return None
    for k, sha in enumerate(shas):
        if k + 1 < len(shas):
            earlier = rows_at(shas[k + 1])
        elif len(shas) == _HISTORY_DEPTH:
            return None   # the change lies further back than we looked
        else:
            earlier = []   # the ledger's first commit
        if rows != earlier:
            out = _git_out(project_dir, 'show', f'{sha}:./scenes/{scene_id}.md')
            return out.decode('utf-8', errors='replace') if out is not None else None
        rows = earlier
    return None


def record_prose(project_dir: str, scene_id: str, prose: str, blocking: str = '') -> str:
    """Record `prose` as what `scene_id`'s commitments were read from: its
    git blob, written to the object store, in `PROSE_PATH`, with how the
    gate run checked its blocking (`blocking`: one of `BLOCKING_METHODS`,
    or '' for not at all; #631, #647). Returns why it couldn't be ('' when
    it was); its row goes then, so a later gate never diffs against the
    wrong prose."""
    if blocking not in ('',) + BLOCKING_METHODS:
        raise ValueError(f'blocking must be one of {", ".join(BLOCKING_METHODS)} or blank, '
                         f'not {blocking!r}')
    blob = _git_out(project_dir, 'hash-object', '-w', '--stdin', data=prose.encode('utf-8'))
    blob_id = blob.decode().strip() if blob else ''
    try:
        rows = _prose_table(project_dir)
    except (OSError, UnicodeDecodeError, ValueError) as e:
        return f'{PROSE_PATH} not updated ({e}); the next re-check counts every reworded fact'
    if blob_id:
        rows[scene_id] = {'blob': blob_id, 'blocking': blocking}
    elif rows.pop(scene_id, None) is None:
        return ''   # no git, and nothing recorded to take back
    path = os.path.join(project_dir, PROSE_PATH)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8', newline='') as f:
            f.write('|'.join(_PROSE_COLUMNS) + '\n')
            for sid in sorted(rows):
                f.write(f'{sid}|{rows[sid]["blob"]}|{rows[sid]["blocking"]}\n')
    except OSError as e:
        return f'{PROSE_PATH} not updated ({e}); the next re-check counts every reworded fact'
    return ''   # no git: the next gate's note says the prose isn't kept


def _paragraphs(text: str) -> list[tuple[str, ...]]:
    return [tuple(_word_list(p)) for p in re.split(r'\n\s*\n', text) if p.strip()]


def _steady_pairs(earlier: str, prose: str) -> dict[int, int]:
    """`steady_paragraphs`, as earlier paragraph index → its index in `prose`."""
    from difflib import SequenceMatcher
    old, new = _paragraphs(earlier), _paragraphs(prose)
    pairs: dict[int, int] = {}
    for tag, i1, i2, j1, _ in SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
        if tag == 'equal':
            for k in range(i2 - i1):
                pairs[i1 + k] = j1 + k
    return {i: j for i, j in pairs.items()
            if (i == 0 and j == 0) or (i > 0 and pairs.get(i - 1) == j - 1)}


def steady_paragraphs(earlier: str, prose: str) -> set[int]:
    """The indexes of `earlier`'s paragraphs that `prose` still has word for
    word (case, punctuation and spacing aside) in the same place: aligned in
    sequence (a moved paragraph is a change), and with the paragraph before
    it unchanged too (the first: still first), since a paragraph reads
    differently after a new antecedent (#558's review)."""
    return set(_steady_pairs(earlier, prose))


def steady_facts(old_rows: list[dict[str, str]], earlier: str, prose: str) -> dict[str, int]:
    """The ids of `old_rows` (commitments read from `earlier`, the prose
    last committed) read from a paragraph `prose` has unchanged and in
    place (`steady_paragraphs`), each with that paragraph's index in
    `prose`: their quote lies within it, or (#632) across unchanged
    paragraphs that follow one another in both (the index of the first). A
    quote not found in `earlier`, or across a changed paragraph, is not
    steady."""
    paras = _paragraphs(earlier)
    pairs = _steady_pairs(earlier, prose)
    # runs of unchanged paragraphs in sequence in both: a quote may span them
    runs, run = [], []
    for i in sorted(pairs):
        if run and not (i == run[-1] + 1 and pairs[i] == pairs[run[-1]] + 1):
            runs.append(run)
            run = []
        run.append(i)
    if run:
        runs.append(run)
    out = {}
    for o in old_rows:
        quote = o.get('quote') or ''
        at = next((j for i, j in pairs.items() if _quote_spans(quote, list(paras[i]))), None)
        if at is None:
            at = next((pairs[r[0]] for r in runs if len(r) > 1
                       and _quote_spans(quote, [w for i in r for w in paras[i]])), None)
        if at is not None:
            out[o['id']] = at
    return out


def _keep_steady(project_dir: str, result: GateResult, old_rows: list[dict[str, str]],
                 prose: str) -> None:
    """#558 (B-032: one deleted phrase, 26 of 27 facts reworded by
    re-extraction and counted as changed, 18 re-checks): keep each earlier
    commitment read from a paragraph the prose still has unchanged and in
    place (`steady_facts`) exactly as it was, same id and statement, and
    drop each proposed row that reads one of them again (one worded
    otherwise is listed in `result.reread`, logged and reported: never a
    silent drop). A proposed row reads a kept
    fact again when its quote lies within one unchanged paragraph and
    either

    - that is the kept fact's paragraph, and it states the same fact or its
      quote shares four words in a row with the kept one's (#558); or
    - (#599) it has the kept fact's subject and type and says nothing the
      kept statement doesn't, or the kept statement says nothing it doesn't
      (`_says_the_same`): a re-check reads prose that hasn't changed at all,
      and extraction may quote another paragraph for a fact the scene has
      ("Tarren's Hollow had 412 people" read again as "... 412 people
      living there").

    A row stating the same fact as an earlier commitment that is not kept
    is never dropped (#599's review, CR-1b): it carries that fact's id
    (`_carry_ids`), and dropping it would delete the fact and re-check its
    dependents though its prose never changed. A row from a changed
    paragraph is never matched to a kept fact (#558's second review: a
    changed paragraph's new fact sharing four words with a kept one was
    dropped, and nothing was re-checked). A row kept as new that reads much
    like a kept fact of its subject and type (`_RESTATES`) is listed in
    `result.restates` for the author to judge. Only the changed paragraphs'
    facts are new readings, so only they can count as changed. A steady fact
    re-extraction left out is kept too, never dropped silently. Without the
    earlier prose (no git, nothing recorded) nothing is kept, and
    `prose_notes` says so. Runs before the hold-back, which leaves the kept
    facts as they are (#632) and reports them."""
    from storyforge.common import log
    if not old_rows:
        return
    earlier, why = gated_prose(project_dir, result.scene_id)
    if earlier is None:
        result.prose_notes.append(f'{result.scene_id}: {why}, so every earlier fact the new '
                                  f'reading words differently counts as changed')
        return
    where = steady_facts(old_rows, earlier, prose)
    kept = [copy.deepcopy(o) for o in old_rows if o['id'] in where]
    if not kept:
        return
    new_paras = _paragraphs(prose)
    steady = set(_steady_pairs(earlier, prose).values())
    # CR-1b: what carries an earlier fact's id is never a re-reading
    not_kept = {ledger.fact_key(o) for o in old_rows if o['id'] not in where}

    def same_fact(p: dict[str, str], o: dict[str, str]) -> bool:
        return (_subject(p) == _subject(o) and (p.get('type') or '') == (o.get('type') or '')
                and _says_the_same(p.get('statement') or '', o.get('statement') or ''))

    def reads_again(p: dict[str, str]) -> dict[str, str] | None:
        """The kept fact `p` reads again, or None."""
        if ledger.fact_key(p) in not_kept:
            return None
        q = p.get('quote') or ''
        at = {j for j, para in enumerate(new_paras) if _quote_spans(q, list(para))}
        if len(at) != 1:
            return None
        j = at.pop()
        if j not in steady:
            return None
        qw = _words(q)
        for o in kept:
            if where[o['id']] == j and (
                    ledger.fact_key(p) == ledger.fact_key(o)
                    or _shared_run(qw, _words(o.get('quote') or '')) >= _MIN_QUOTE_WORDS):
                return o
        return next((o for o in kept if same_fact(p, o)), None)

    # #749's review CR-1: a kept fact a claim in speech reads again is a
    # claim now, never in force: not kept, so it counts as changed and what
    # leaned on it is re-checked
    as_claims = {o['id']: o for o in filter(None, map(reads_again, result.claims))}
    if as_claims:
        kept = [o for o in kept if o['id'] not in as_claims]
        result.unkept_as_claims = [(rid, o.get('statement') or '')
                                   for rid, o in as_claims.items()]
        log(f'  NOTE: {result.scene_id}: read now as a claim in speech, no longer kept: '
            + ', '.join(as_claims))
    fresh = []
    for p in result.proposed:
        o = reads_again(p)
        if o is None:
            fresh.append(p)
            continue
        if ledger.fact_key(p) == ledger.fact_key(o):
            continue   # the kept fact word for word: nothing is lost
        result.reread.append((p.get('statement') or '', o['id']))
        log(f'  NOTE: {result.scene_id}: not recorded, a reading again of {o["id"]} '
            f'(unchanged prose): "{_one_line(p.get("statement") or "")[:160]}"')
    for p in fresh:
        o = next((o for o in kept if _subject(p) == _subject(o)
                  and (p.get('type') or '') == (o.get('type') or '')
                  and _overlap(p.get('statement') or '', o.get('statement') or '')
                  >= _RESTATES), None)
        if o is not None:
            result.restates.append((p.get('statement') or '', o['id']))
            log(f'  NOTE: {result.scene_id}: recorded as a new fact, but it reads much like '
                f'{o["id"]}; check it is not a copy: "'
                f'{_one_line(p.get("statement") or "")[:160]}"')
    result.proposed = kept + fresh
    result.steady = [o['id'] for o in kept]


def _here_registry_ids(rows: list[dict[str, str]], scene_id: str) -> set[str]:
    """The registry (plan) facts recorded for `scene_id`."""
    return {r['id'] for r in rows if not ledger.is_commitment(r)
            and (r.get('scene_id') or '').strip() == scene_id}


def _ended_here(commitments: list[dict[str, str]], here_ids: set[str]) -> set[str]:
    """The plan facts of the scene its commitments end (#734): an end of a
    state set up in the scene is recorded as a commitment that supersedes it
    (`_apply_ends`)."""
    return {old for r in commitments for old in ledger._split(r.get('supersedes', ''))
            if old in here_ids}


def _apply_ends(project_dir: str, result: GateResult, rows: list[dict[str, str]],
                old_rows: list[dict[str, str]], prose: str, loaded=(), held=()) -> None:
    """The ends extraction read (`result.ends`; #734's review CR-5), applied
    on commit. An offered state's end sets its `resolves` to the scene. An
    `ENDS_HERE` claim, on a state the plan sets up in the scene, is never
    written on the plan's row (the author's; #734's review CR-2): it is a
    commitment of the scene, the plan fact's subject, type and statement
    with the carrying fact's quote, that supersedes the plan fact and
    resolves here, so the state isn't in force after the scene and a
    re-gate, which replaces the scene's commitments, reads it afresh. One is
    recorded only when the check found the scene shows the state ending
    (`check.ended`, a ruling of its own: #734's re-review, SF-1), the fact that ends it is committed (not
    held back, not dropped as a reading again) with its quote in the scene,
    and, on prose with every paragraph unchanged, the earlier version ended
    it too (`_keep_steady_ends`' rule). One already recorded by a kept
    (steady) commitment stays. Each not recorded is in `ends_held`, with
    why; each recorded in `problems[ENDS_HERE]`."""
    from storyforge.extract import ENDS_HERE, commitment_id
    from storyforge.quotes import quote_in
    scene_id = result.scene_id
    by_id = {r['id']: r for r in rows}
    def disputed(carrier) -> bool:
        return any(r is carrier for r in result.disputed_rows)

    for e in result.ends:
        if e.kind != ENDS_HERE and e.state_id in by_id:
            if disputed(e.carrier):
                # #735's review CR-1: a disputed fact ends nothing while it is
                # held; its stamp keeps the end for `accept_blocked`
                keys, ends = held_parts(e.carrier.get('reviewed', ''))
                if e.state_id not in ends:
                    e.carrier['reviewed'] = held_stamp(keys, ends + [e.state_id])
                result.ends_held.append(f'{e.state_id}: the fact that ends it is recorded '
                                        f'as disputed; ended when it comes into force')
                continue
            by_id[e.state_id]['resolves'] = scene_id
    claims = [e for e in result.ends if e.kind == ENDS_HERE]
    if not claims:
        return
    here_ids = _here_registry_ids(rows, scene_id)
    already = _ended_here(result.proposed, here_ids)
    # an end a disputed row of the earlier version recorded counts (#735's
    # review CR-2): accepted, then gated again on the same prose, it stays
    before = _ended_here(list(old_rows) + list(held), here_ids)
    confirmed = {d.fact_id for d in result.check.ended} if result.check else set()
    earlier, _ = gated_prose(project_dir, scene_id)
    unchanged = earlier is not None and _paragraphs(earlier) == _paragraphs(prose)
    taken = ({r['id'] for r in rows} | {r['id'] for r in result.proposed}
             | {r['id'] for r in result.disputed_rows}
             | {r['id'] for r in old_rows} | {r['id'] for r in loaded}
             | ledger.linked_ids(list(loaded)))
    for e in claims:
        if e.state_id in already:
            continue
        quote = e.carrier.get('quote', '')
        held_end = disputed(e.carrier)
        if e.state_id not in confirmed:
            why = 'the check did not find the scene shows it ending'
        elif unchanged and e.state_id not in before:
            why = 'unchanged prose, and the earlier version did not end it'
        elif not held_end and not any(r is e.carrier for r in result.proposed):
            why = ('the fact that ends it was not recorded (a contradiction already in the '
                   'scene, or a reading again of unchanged prose)')
        elif not quote or not quote_in(prose, quote):
            why = 'the quote of the fact that ends it is not in the scene'
        else:
            why = ''
        if why:
            result.ends_held.append(f'{e.state_id}: {why}')
            continue
        state = by_id[e.state_id]
        end = {c: '' for c in ledger.COLUMNS}
        end.update(id=commitment_id(scene_id, state.get('statement', ''), taken),
                   scene_id=scene_id, type=state.get('type', ''),
                   subject=state.get('subject', ''), statement=state.get('statement', ''),
                   quote=quote, origin='prose', status='binding', mutable='state',
                   supersedes=e.state_id, resolves=scene_id,
                   introduced_by=e.carrier.get('introduced_by', ''))
        taken.add(end['id'])
        if held_end:
            # #735's review CR-2: recorded with its carrier, as disputed (the
            # same finding keys), and in force with it
            keys, _ = held_parts(e.carrier.get('reviewed', ''))
            end.update(status='pending', reviewed=held_stamp(keys))
            result.disputed_rows.append(end)
            result.ends_held.append(f'{e.state_id}: carrier recorded as disputed; the end '
                                    f'is recorded with it, in force when it is')
            continue
        result.proposed.append(end)
        result.problems.setdefault(ENDS_HERE, []).append(
            f'{scene_id}: {e.state_id} (by {e.carrier.get("id", "")})')


def _keep_steady_ends(project_dir: str, result: GateResult, new: list[dict[str, str]],
                      ended_before: set[str], loaded, prose: str,
                      claimed: Set[str] = frozenset()) -> None:
    """#632: on prose with every paragraph unchanged since the scene's last
    gate (`gated_prose`), the earlier states the scene ended stay ended
    here and no others are, whatever the new reading's `ends` say: a
    re-extraction of the same words that dropped or added an `ends` link
    counted as a change and listed the later scenes for a re-check. An end
    the new reading dropped is put back (on a state still open); one it
    added on an open state is not applied. An end moved here from a later
    scene (#621, `ENDS_MOVED`) is left as extraction made it. Each is said
    in `prose_notes`. On prose with any paragraph changed, nothing here can
    tell which paragraph an end was read from, so every change counts.
    `claimed` (#735's review CR-2): the ends the earlier version's disputed
    facts recorded; one applied now that its fact is in force stays."""
    now = ledger.ended_by(new, result.scene_id)
    if not ended_before ^ now:
        return
    earlier, _ = gated_prose(project_dir, result.scene_id)
    if earlier is None or _paragraphs(earlier) != _paragraphs(prose):
        return
    was = {r['id']: (r.get('resolves') or '').strip() for r in loaded}
    by_id = {r['id']: r for r in new}
    for rid in sorted(ended_before - now):
        r = by_id.get(rid)
        if r is not None and not (r.get('resolves') or '').strip():
            r['resolves'] = result.scene_id
            result.prose_notes.append(f'{result.scene_id}: kept its end of {rid} (unchanged '
                                      f'prose; the new reading left it out)')
    for rid in sorted(now - ended_before - set(claimed)):
        r = by_id.get(rid)
        if r is not None and not was.get(rid):
            r['resolves'] = ''
            result.prose_notes.append(f'{result.scene_id}: did not apply a new end of {rid} '
                                      f'(unchanged prose; the earlier reading had none)')


def _subject(row: dict[str, str]) -> str:
    return (row.get('subject') or '').strip().casefold()


#: Words that carry no fact of their own (#599): left out when two
#: statements are compared (`_content_words`)
_FUNCTION_WORDS = frozenset(
    'a an the and or but nor of to in on at by for from with into onto upon as is are was '
    'were be been being has have had do does did that this these those it its his her hers '
    'their theirs him them he she they i you we me my your our us who whom whose which what '
    'when where while than then so there s t'.split())

#: `_overlap` at or above which a new fact is listed as reading much like a
#: kept one (`GateResult.restates`). The pilot's (#599): the scab "split open
#: and bled" / "splits and bleeds a thin line of blood" 0.54; Medon's warning
#: reworded 0.65; "Telemachus tells Pisistratus ..." 0.58, but its subjects
#: differ, so it isn't compared. A survey that "marked a temple" / "marked a
#: well" is 0.71 too: overlap can't tell a rewording from a different fact,
#: which is why it only lists, and `_says_the_same` decides a drop
_RESTATES = 0.5


def _content_words(statement: str) -> set[str]:
    """`statement`'s words less `_FUNCTION_WORDS`, lowercased, with a plural
    or tense ending taken off (-s, -es, -ed, -ing; three letters kept)."""
    out = set()
    for w in re.findall(r'[a-z0-9]+', statement.lower()):
        if w in _FUNCTION_WORDS:
            continue
        for end in ('ing', 'ed', 'es', 's'):
            if w.endswith(end) and not w.endswith('ss') and len(w) - len(end) >= 3:
                w = w[:-len(end)]
                break
        out.add(w)
    return out


def _says_the_same(a: str, b: str) -> bool:
    """Whether one statement says nothing the other doesn't: the content
    words of one all in the other's (`_content_words`). Containment, not a
    similarity score (#599's review): "marked a temple" and "marked a well"
    share all but one word and are different facts; "had 412 people" and
    "had 412 people living there" are one. A rewording that changes words
    ("split open and bled" / "splits and bleeds") is not the same by this
    test; it is kept, and listed in `restates`."""
    wa, wb = _content_words(a), _content_words(b)
    return bool(wa) and bool(wb) and (wa <= wb or wb <= wa)


def _overlap(a: str, b: str) -> float:
    """The content words two statements share, of all they have (Jaccard)."""
    wa, wb = _content_words(a), _content_words(b)
    return len(wa & wb) / len(wa | wb) if wa | wb else 0.0


def _shared_run(a: str, b: str) -> int:
    """The longest run of words two `_words` strings share."""
    from difflib import SequenceMatcher
    aw, bw = a.split(), b.split()
    return SequenceMatcher(None, aw, bw, autojunk=False).find_longest_match(
        0, len(aw), 0, len(bw)).size


def _gone_scenes(project_dir: str) -> set[str]:
    from storyforge.elaborate import get_scenes
    from storyforge.prompts import _GONE
    return {r['id'] for r in get_scenes(os.path.join(project_dir, 'reference'))
            if (r.get('status') or '').strip().lower() in _GONE}


def _has_prose(project_dir: str, scene_id: str) -> bool:
    """Whether the scene has prose: a file of illustration markers alone
    has none, as `prompts._has_prose` says (#610's review, T-2)."""
    from storyforge.illustrations import read_scene_prose
    path = os.path.join(project_dir, 'scenes', f'{scene_id}.md')
    try:
        return bool(read_scene_prose(path).strip())
    except OSError:
        return False


def _carry_ids(proposed: list[dict[str, str]], old_rows: list[dict[str, str]],
               steady: list[str]) -> None:
    """Give each proposed row that states the same fact as one of the
    scene's earlier commitments (`ledger.fact_key`) that row's id, and its
    end in a later scene when the new row has none: links to it (a later
    `supersedes`, the later scene's end) keep holding. A kept row (#558,
    its id in `steady`) keeps its own id. Every other row keeps the id
    extraction gave it, which no earlier commitment of the scene and no
    other row has (`_extract`'s `reserved`, #599: an old id not carried is
    never reused, or a later link to it would land on a different fact).
    Links between proposed rows follow the renames. In place.

    Raises:
        GateError: a row neither kept nor carried has an earlier
            commitment's id (it was minted without `reserved`; #599's
            review, TD-2): nothing is written.
    """
    kept_ids = set(steady)
    old_ids = {o['id'] for o in old_rows}
    by_key: dict[tuple, dict[str, str]] = {}
    for o in old_rows:
        by_key.setdefault(ledger.fact_key(o), o)
    unchanged = [p['id'] in kept_ids for p in proposed]   # kept as it was (#558)
    # by position, never by id: a kept steady row (#558) and a new row
    # stating the same fact are two rows (Beowulf B-034)
    carried = set(kept_ids)
    rename: dict[str, str] = {}
    for p, kept in zip(proposed, unchanged):
        if kept:
            continue
        o = by_key.get(ledger.fact_key(p))
        if o is None or o['id'] in carried:
            if p['id'] in old_ids:
                raise GateError(f'{p.get("scene_id") or "?"}: new fact {p["id"]!r} has the id '
                                f'of an earlier commitment of the scene (minted without the '
                                f'reserved ids); nothing written')
            continue
        carried.add(o['id'])
        rename[p['id']] = o['id']
        p['id'] = o['id']
        if not (p.get('resolves') or '').strip() and ledger._ends_elsewhere(o):
            p['resolves'] = o['resolves']
    # links between extraction's rows follow its renames; a kept row's links
    # are the ledger's and stay
    for p, kept in zip(proposed, unchanged):
        if kept:
            continue
        for col in ('supersedes', 'depends_on'):
            refs = ledger._split(p.get(col, ''))
            if any(r in rename for r in refs):
                p[col] = ';'.join(rename.get(r, r) for r in refs)


# ============================================================================
# Fix (plan §3.2 step 3): targeted edits and a re-check, up to FIX_ROUNDS times
# ============================================================================

FIX_SCHEMA = {
    'type': 'object',
    'properties': {'edits': {'type': 'array', 'items': {
        'type': 'object',
        'properties': {'problem': {'type': 'integer'}, 'find': {'type': 'string'},
                       'replace': {'type': 'string'}},
        'required': ['problem', 'find', 'replace'],
        'additionalProperties': False,
    }}},
    'required': ['edits'],
    'additionalProperties': False,
}


def problems_to_fix(result: GateResult) -> list[str]:
    """What a fix should address, one line each: halts (with the scene's
    words that set the fact), contradictions and broken promises, and
    unverified findings, marked as such with why their quotes failed. An
    extraction problem isn't a prose problem, so it isn't here: the re-check
    extracts again. Neither is a halt the plan calls for (#788: the change
    is the scene, so the fixed fact is likely mis-typed), a plan conflict (the brief's own words: an
    edit would break the promise), an inherited contradiction (the
    author's, from before the pass) or an advisory broken promise (#642:
    the prose wins over a beat the brief doesn't mark `must:`)."""
    proposed = {r['id']: r for r in result.proposed}
    lines = []
    for h in result.halts:
        if h.planned:
            continue    # #788: the change is the scene; the author's to unfix
        row = proposed.get(h.fact_id)
        said = (f' The scene says: "{row.get("quote") or row.get("statement")}".'
                if row else '')
        lines.append(f'The scene changes something the book fixed: {h.detail}.{said}')
    for item in result.problems.get('rejected', []):
        lines.append(f'The scene restates a fact the author rejected; change or remove it: '
                     f'{item}')
    for f, unverified in ([(f, False) for f in result.fixable]
                          + [(f, True) for f in result.unverified]):
        tag = (f'UNVERIFIED (the check\'s quotes did not hold up: {f.problem}; edit only '
               f'if the scene clearly contradicts the book) ' if unverified else '')
        if f.code == BLOCKING_CODE:
            # The scene against itself (#626): either side may be the slip
            against = (f', against "{f.established_quote}" in the same scene'
                       if f.established_quote and f.established_quote != f.scene_quote else '')
            lines.append(f'{tag}{f.code} blocking: the scene says "{f.scene_quote}"{against}. '
                         f'{f.explanation}')
        elif f.kind == 'contradiction':
            lines.append(f'{tag}{f.code} contradiction: the scene says "{f.scene_quote}", '
                         f'but {f.source} establishes "{f.established_quote}". {f.explanation}')
        else:
            lines.append(f'{tag}Broken promise ({f.fact_id}): the brief promises '
                         f'"{f.established_quote}". {f.explanation}'
                         + (f' Nearest words: "{f.scene_quote}".' if f.scene_quote else ''))
    return lines


#: How many rounds `gate_and_fix` runs on a scene that still fails, each a
#: fix and its re-check (or, for a first run with nothing for the fix, a
#: re-roll with no edit). A second round sees what the first changed: one
#: fix often moves a wrong value to another wrong one ("eight days" to
#: "five") or fixes half a pronoun. Not a cap on gate runs: a partial fix
#: (`_partial_fix`) and a re-extraction (`_reextract`, #598) are runs
#: besides the rounds.
FIX_ROUNDS = 2


@dataclass
class FixRound:
    """One fix `gate_and_fix` made: the problems it was sent and its edits."""
    problems: list[str]
    edits: list[dict]


def build_fix_prompt(scene_id: str, prose: str, problems: list[str],
                     protected: list[str] | tuple = (),
                     earlier: list[FixRound] | tuple = ()) -> str:
    """The fix's prompt. `protected`: the brief's own words in the scene
    (`_brief_phrases`), which an edit must leave as they are. `earlier`: the
    fixes already made to this prose, which the check still failed."""
    listing = '\n'.join(f'{n}. {p}' for n, p in enumerate(problems, start=1))
    keep = ''
    if protected:
        keep = ('\n## Lines the brief scripts\n\nThe scene must keep these words exactly; '
                'no edit may change or remove them:\n\n'
                + '\n'.join(f'- "{p}"' for p in protected) + '\n')
    tried = ''
    if earlier:
        parts = []
        for r in earlier:
            parts.append('Problems sent:\n' + '\n'.join(f'- {p}' for p in r.problems))
            parts.append('Edits made:\n' + ('\n'.join(
                f'- "{e.get("find", "")}" became "{e.get("replace", "")}"' for e in r.edits)
                or '- none'))
        tried = ('\n## Earlier fixes\n\nThe scene below already has these edits, and the '
                 'check still found the problems above. Keep what an earlier edit fixed. '
                 'Where an earlier edit put in a value that is still wrong, don\'t guess '
                 'again: take the value the problem quotes from the book, or remove the '
                 'detail. Where it changed only part of something (one pronoun of several, '
                 'one mention of a name), change the rest.\n\n' + '\n\n'.join(parts) + '\n')
    blocking = ''
    if any(f'{BLOCKING_CODE} blocking:' in p for p in problems):
        blocking = ('- A BLK blocking problem is the scene against itself, not against the book: '
                    'change whichever side is the slip, with the fewest words that make the '
                    'action physically possible (free the hand before it does something else, '
                    'name the right hand or side, add the movement that was skipped).\n')
    return f"""A continuity check found these problems in scene {scene_id}. Fix each with the smallest edit to the scene's prose that resolves it.

## Problems

{listing}
{keep}{tried}
## Rules

- Change the scene so it agrees with what the book established; never assume the established fact is the one that is wrong. A problem marked UNVERIFIED may be the check's mistake: edit for it only if the scene clearly contradicts the book.
- Take the book's value, never a new one. When a name, number, age, date, duration, place or relationship is wrong, use the one the problem quotes from the book. If the problem doesn't say what the right value is, remove the detail or make it vague ("years ago", "a neighbour") instead of choosing another: any new specific you invent is one more thing that can contradict the book.
- Fix the scene's words, not the book's people: don't rename a character, change who someone is, or move an event to make a contradiction go away.
{blocking}- A broken promise: add or change the fewest words that deliver it, in the scene's voice, where it fits the action.
- Each edit replaces `find`, words copied exactly from the scene that occur in it once, with `replace`. Keep `find` short: the sentence or clause that changes. Edits must not overlap.
- Change nothing else: no polishing, no other improvements. `problem` is the number of the problem the edit fixes.
- If a problem is a false alarm (the scene does not actually contradict anything), make no edit for it.

## Scene {scene_id}

{prose}"""


def apply_edits(prose: str, edits: list[dict], layout: bool = True) -> str:
    """`prose` with each edit's `find` replaced. A `find` is placed by
    `scene_layout.find_span`: exactly once, or, when it isn't there exactly,
    once with its whitespace loosened within a prose paragraph (a space for
    a sentence's line break); spaces around it are matched only when the
    replacement has them too. `layout`: the paragraphs the edits changed
    are laid out a sentence per line (`scene_layout.sentence_lines`, with
    the prose as `old`: the rest keep their bytes); False keeps the text's
    own layout (a voice sample).

    Raises:
        GateError: a `find` can't be placed (missing, or in more than one
            place, exactly or loosened), or overlaps another edit's;
            nothing is applied then.
    """
    from storyforge.scene_layout import find_span, sentence_lines
    spans = []
    for e in edits:
        find = (e.get('find') or '').replace('\r\n', '\n')
        if '\r\n' in prose:
            find = find.replace('\n', '\r\n')
        replace = e.get('replace') or ''
        found = find_span(prose, find)
        if found.span is None:
            raise GateError(f'a fix edit\'s text occurs {found.problem(find)}')
        if not found.exact:   # loosened: its own padding isn't in the scene
            lead, trail = find[:len(find) - len(find.lstrip())], find[len(find.rstrip()):]
            if lead and replace.startswith(lead):
                replace = replace[len(lead):]
            if trail and replace.endswith(trail):
                replace = replace[:len(replace) - len(trail)]
        spans.append((*found.span, replace))
    spans.sort()
    for (_, end, _), (start, _, _) in zip(spans, spans[1:]):
        if start < end:
            raise GateError('two fix edits overlap')
    new = prose
    for start, end, replace in reversed(spans):
        new = new[:start] + replace + new[end:]
    return sentence_lines(new, old=prose) if layout and edits else new


class Fixer(Protocol):
    """What `gate_and_fix` calls to fix a scene (`fix_scene`, or a writing
    session's writer, #655): the fixed prose; the edits applied appended to
    `edits_out` only once they all applied; `GateError` on any failure.
    `log_dir` and `model` may be ignored (a session logs to its own folder
    and fixes with its writer). A fixer never writes its spend to the cost
    ledger: `gate_and_fix` meters the call and logs it as `gate-fix` (#716)."""

    def __call__(self, scene_id: str, prose: str, result: 'GateResult', *, log_dir: str,
                 model: str | None = None, protected: list[str] | tuple = (),
                 earlier: list['FixRound'] | tuple = (),
                 edits_out: list[dict] | None = None) -> str: ...


def fix_scene(scene_id: str, prose: str, result: GateResult, *, log_dir: str,
              model: str | None = None, protected: list[str] | tuple = (),
              earlier: list[FixRound] | tuple = (),
              edits_out: list[dict] | None = None) -> str:
    """The scene with targeted edits for `result`'s problems (one model call).
    `earlier`: the fixes already made (`build_fix_prompt`). The edits applied
    are appended to `edits_out` when it is given (only once they all applied;
    nothing when there was nothing to fix).

    Raises:
        GateError: the call failed, the reply was cut off or not the schema,
            or an edit can't be applied (`apply_edits`).
    """
    import json
    from storyforge.api import extract_text, invoke_to_file, is_truncated
    from storyforge.common import select_model
    problems = problems_to_fix(result)
    if not problems:
        return prose
    log_file = os.path.join(log_dir, f'gate-fix-{scene_id}.json')
    try:
        response = invoke_to_file(build_fix_prompt(scene_id, prose, problems, protected,
                                                   earlier),
                                  model or select_model('revision'), log_file, 8000,
                                  output_schema=FIX_SCHEMA, label=f'fix {scene_id}')
        if is_truncated(response):
            raise ValueError('the reply hit its token limit')
        edits = json.loads(extract_text(response))['edits']
    except (RuntimeError, ValueError, KeyError, TypeError) as e:
        raise GateError(f'{scene_id}: the fix failed: {e}') from e
    fixed = apply_edits(prose, edits)
    if edits_out is not None:
        edits_out.extend(edits)
    return fixed


@dataclass
class GatedScene:
    """`gate_and_fix`'s answer: the prose to keep and the gate's last word."""
    prose: str
    result: GateResult          # the last gate run kept (a re-check when there was one)
    first: GateResult           # the first gate run
    # whether .prose differs from the prose given (the caller writes .prose
    # only then); not `bool(rounds)`: a later fix can undo an earlier one
    fixed: bool = False
    rounds: list[FixRound] = field(default_factory=list)  # the fixes kept, in order
    #: what the caller must log: the round discarded and why (its prose and
    #: verdict are not what's kept), and findings a round couldn't place
    notes: list[str] = field(default_factory=list)
    #: the fix round whose fix was discarded (0: none); `rounds` holds the
    #: ones kept, so 1 with no rounds means the scene is as given
    discarded: int = 0
    #: how many new findings the discarded fix's check made in words it
    #: left alone: in the prose kept too, not in the verdict kept (#737's
    #: review SF-4: the pending reason says so)
    unseen: int = 0
    #: why `BLOCKED_PATH` couldn't be put back to the kept run's
    #: contradictions after a discard ('' when it was): the caller says so
    blocked_stale: str = ''
    #: this invocation's logs (`run_log_dir`): the first run's, each
    #: re-check's in `recheck/`, `recheck-2/` (round 1's re-roll's in
    #: `recheck/`), and `_reextract`'s in `reextract/`
    log_dir: str = ''
    #: the gate run of unchanged prose made because only the extractor's
    #: slips stopped the run before it (round 1's re-roll of such a run, or
    #: `_reextract`; #598), and how it came out; None when there was none
    #: (a re-roll for other extraction problems isn't one). The caller logs
    #: `.summary()` and puts it in a pending reason, so a misquote is never
    #: read as the prose's problem
    reextraction: 'Reextraction | None' = None


#: `Reextraction.outcome`s
REGATE_PASSED = 'passed'
REGATE_FAILED = 'failed'
REGATE_ERROR = 'error'


@dataclass
class Reextraction:
    """A gate run of the same prose after the extractor misquoted it (#598)."""
    slips: list[str]            # the run before it's slips (`_describe_slips`)
    outcome: str                # REGATE_PASSED, REGATE_FAILED or REGATE_ERROR
    #: REGATE_FAILED: the second run's own slips (both runs' are reported,
    #: #602's review SF-4), and whether anything else stopped it
    again: list[str] = field(default_factory=list)
    others: bool = False
    error: str = ''             # REGATE_ERROR: why the run couldn't finish
    #: #734: how many of the run before it's findings stood in it (its slips
    #: were beside them; `_reextract(standing=True)`)
    standing: int = 0
    #: the facts the second run misquoted again and held back
    #: (`GateResult.slips_held`): not recorded, not a stop
    held: list[str] = field(default_factory=list)

    @classmethod
    def of(cls, run: GateResult, again: GateResult | None = None,
           error: str = '') -> 'Reextraction':
        slips = _describe_slips(run)
        if again is None:
            return cls(slips, REGATE_ERROR, error=error)
        held = list(again.slips_held)
        if again.passed:
            return cls(slips, REGATE_PASSED, held=held)
        return cls(slips, REGATE_FAILED, again=_describe_slips(again),
                   others=not _only_extractor_slips(again), held=held)

    def summary(self) -> str:
        said = (f'the extractor {_slipped(self.slips)} ({_slip_text(self.slips)}), so the same '
                f'prose was gated again (extraction and the check'
                + (f', the {self.standing} finding(s) before it standing' if self.standing
                   else '') + ')')
        held = (f'it misquoted the prose again ({_slip_text(self.held)}): held back, not '
                f'recorded, and the scene not stopped for the gate\'s own slip'
                if self.held else '')
        if self.outcome == REGATE_PASSED:
            return f'{said}: ' + (f'{held}; it passed' if held else 'it passed')
        if self.outcome == REGATE_ERROR:
            return (f'{said}, which could not finish ({_one_line(self.error)}); the verdict '
                    f'before it stands')
        parts = [held] if held else []
        if self.again:
            parts.append(f'it {_slipped(self.again)} again ({_slip_text(self.again)}); no quote '
                         f'is replaced with the prose\'s words')
        if self.others:
            parts.append('it stopped on other problems (listed)')
        return f'{said}: ' + '; '.join(parts)


def _blocking_count(result: GateResult) -> int:
    return len(blocking_lines(report_lines(result)))


def _undone_edit(earlier: list[FixRound] | tuple, before: str, after: str) -> str | None:
    """The `find` of an earlier fix's edit that a later fix put back: words the
    earlier edit removed, absent from `before`, present again in `after`
    (whitespace aside: a scene is a sentence per line, a `find` may not be)."""
    def flat(text: str) -> str:   # a sentence per line: compare across line breaks
        return ' '.join(text.split())
    before, after = flat(before), flat(after)
    for r in earlier:
        for e in r.edits:
            find, replace = e.get('find') or '', e.get('replace') or ''
            f = flat(find)
            if f and f not in flat(replace) and f not in before and f in after:
                return find
    return None


def _word_list(text: str) -> list[str]:
    from storyforge.checker import normalize
    return re.findall(r'\w+', normalize(text).lower())


class Span(NamedTuple):
    """Words [start, end) of a prose's word list (`_word_list`); an empty
    span marks the place between two words."""
    start: int
    end: int


@dataclass
class _Diff:
    """What a fix changed, as a word diff of the prose before and after it,
    computed once per round (`_diff`): the changed spans on each side
    (words put in, replaced or taken out; an empty span where words were
    only added on the other side)."""
    before: list[str]
    after: list[str]
    before_spans: list[Span]
    after_spans: list[Span]
    #: `_word_offsets` of each prose, for `_untouched`'s punctuation test
    #: (#737's review CR-2); None in a diff built by hand
    before_flat: tuple | None = None
    after_flat: tuple | None = None


def _diff(before: str, after: str) -> _Diff:
    from difflib import SequenceMatcher
    old, new = _word_list(before), _word_list(after)
    ops = [op for op in SequenceMatcher(None, old, new, autojunk=False).get_opcodes()
           if op[0] != 'equal']
    return _Diff(old, new, [Span(i1, i2) for _, i1, i2, _, _ in ops],
                 [Span(j1, j2) for _, _, _, j1, j2 in ops],
                 _word_offsets(before), _word_offsets(after))


def _quote_spans(quote: str, words: list[str]) -> list[Span]:
    """Every place `quote` (its parts, split at an ellipsis, in order) is in
    `words`."""
    parts = [p for p in (_word_list(x) for x in re.split(r'\.\.\.|…', quote)) if p]
    if not parts:
        return []

    def at(part: list[str], start: int) -> int:
        for i in range(start, len(words) - len(part) + 1):
            if words[i:i + len(part)] == part:
                return i
        return -1
    out, first = [], parts[0]
    for i in range(len(words) - len(first) + 1):
        if words[i:i + len(first)] != first:
            continue
        end, ok = i + len(first), True
        for part in parts[1:]:
            j = at(part, end)
            if j < 0:
                ok = False
                break
            end = j + len(part)
        if ok:
            out.append(Span(i, end))
    return out


#: How many unchanged words must lie between a quote and every change for
#: the quote to count as away from the fix (`_touches(near=True)`): a word
#: diff can line a change up a word or two off where the edit was
#: ("forty-one, the morning after. The coffee" against "forty-one. The
#: coffee" matches the two "the"s). Tuned on a handful of E4/E8 replays
#: (2026-11-03), not measured
_NEAR_WORDS = 4


def _touches(span: Span, changed: list[Span], near: bool = False) -> bool:
    """Whether `span` overlaps a changed span (an empty one: lies strictly
    inside it); with `near`, whether fewer than `_NEAR_WORDS` unchanged
    words lie between it and a changed span."""
    s, e = span
    if near:
        return any(a - _NEAR_WORDS < e and s < b + _NEAR_WORDS for a, b in changed)
    return any((a < e and s < b) if a < b else (s < a < e) for a, b in changed)


def _in_untouched_text(f: Finding, diff: '_Diff', before: bool = False) -> bool:
    """Whether `f`'s scene quote lies only in text the fix left alone, in
    the prose after the fix (or with `before`, the prose before it): found
    there, and `_untouched` (no place near a change, its punctuation
    unchanged). A quote not found: no (it may be about the change)."""
    return _place(*_side(f.scene_quote, diff, before)) == ALONE


def _side(quote: str, diff: '_Diff', before: bool = False) -> tuple:
    """`_place`'s arguments for `quote` on one side of `diff`."""
    if before:
        return (_quote_spans(quote, diff.before), diff.before_spans, diff.before_flat,
                diff.after_flat)
    return (_quote_spans(quote, diff.after), diff.after_spans, diff.after_flat,
            diff.before_flat)


#: Where a re-check's finding lies relative to a fix (`_placement`)
EDITED, NEAR, ALONE, UNPLACED = 'edited', 'near', 'alone', 'unplaced'


def _place(places: list[Span], changed: list[Span], own: tuple | None = None,
           other: tuple | None = None) -> str:
    """`EDITED` when every place touches a changed span, `ALONE` when they
    are away from the fix (`_untouched`: none near a change, punctuation
    beside each unchanged), else `NEAR`; `UNPLACED` with no place."""
    if not places:
        return UNPLACED
    if all(_touches(p, changed) for p in places):
        return EDITED
    if _untouched(places, changed, own, other):
        return ALONE
    return NEAR


def _kept_places(f: Finding, before_run: GateResult | None, words: list[str]) -> list[Span]:
    """Where the run before the fix found the promise `f` breaks kept: the
    quotes its check gave that registry fact (`kept`, and `kept_unverified`
    when the quote is in the prose but short), found in `words` (the prose
    before the fix). A brief field's promise names no fact (`fact_id` is
    the field), so none."""
    from storyforge.checker import _FIELD_PROMISES
    check = before_run.check if before_run else None
    if f.kind != 'broken-promise' or not check or not f.fact_id or (
            f.fact_id in _FIELD_PROMISES):
        return []
    quotes = [q for rid, q in check.kept if rid == f.fact_id]
    quotes += [q for rid, q, *_ in check.kept_unverified if rid == f.fact_id]
    return [p for q in quotes if q.strip() for p in _quote_spans(q, words)]


def _took_out_its_words(f: Finding, diff: '_Diff') -> bool:
    """Whether the fix changed a broken promise's own words: four words in
    a row of its `established_quote` (the brief's line, or the registry
    fact) were in the prose before the fix where it changed words, as
    `_bad_edits` ties a promise to an edit's `find`."""
    if f.kind != 'broken-promise' or not f.established_quote:
        return False
    promise = _word_list(f.established_quote)
    runs = {tuple(promise[i:i + 4]) for i in range(len(promise) - 3)}
    return any(_touches(p, diff.before_spans)
               for run in runs for p in _quote_spans(' '.join(run), diff.before))


def _placement(f: Finding, before_run: GateResult | None, diff: '_Diff',
               by_kept: bool = True) -> str:
    """Where the re-check's finding `f` lies relative to the fix `diff`
    (#737):

    - its scene quote, in the fixed prose: `EDITED` (every place it is
      found touches words the fix changed), `ALONE` (no place comes within
      `_NEAR_WORDS` of a change), or `NEAR`;
    - a broken promise with no quote there (the question layer gives
      none; a fix that takes out the words keeping a promise leaves none
      to give) is `EDITED` when the fix changed its own words (four in a
      row of them, `_took_out_its_words`), whatever a kept quote says:
      words taken out are evidence about this prose, a kept quote is the
      run before's reading of one place (#737's review CR-3). Otherwise,
      with `by_kept`, it is placed by where the run before found the
      promise kept (`_kept_places`), measured on the prose before the fix:
      those words unchanged are `ALONE` (the same words, read again),
      changed or next to a change `EDITED` or `NEAR`;
    - anything else `UNPLACED`: nothing ties it to the edits or clears it
      of them.

    `by_kept` is False for a finding the run before already had (#737's
    review SF-1): it was counted there by its scene quote alone, and must
    be counted the same way after, or a promise both kept and broken by
    two readings drops out of one side of the count only."""
    where = _place(*_side(f.scene_quote, diff))
    if where != UNPLACED or f.kind != 'broken-promise':
        return where
    if _took_out_its_words(f, diff):
        return EDITED
    if not by_kept:
        return UNPLACED
    return _place(_kept_places(f, before_run, diff.before), diff.before_spans,
                  diff.before_flat, diff.after_flat)


def _new_findings(before_run: GateResult, after_run: GateResult) -> list[Finding]:
    """`after_run`'s blocking findings that aren't a problem `before_run`
    already had (`_persists`)."""
    earlier = list(before_run.check.findings + before_run.check.unverified
                   if before_run.check else [])
    return [f for f in after_run.findings + after_run.unverified
            if not _persists(f, earlier)]


def _alone(before_run: GateResult, after_run: GateResult, diff: '_Diff') -> list[Finding]:
    """`after_run`'s new findings (`_new_findings`) in words the fix left
    alone (`_placement` `ALONE`): not the fix's. They stand in the run kept,
    for the next round or the author, and `gate_and_fix` names them."""
    return [f for f in _new_findings(before_run, after_run)
            if _placement(f, before_run, diff) == ALONE]


def _unplaced(before_run: GateResult, after_run: GateResult, diff: '_Diff') -> list[Finding]:
    """`after_run`'s new findings that can't be placed relative to the fix
    (`_placement` `UNPLACED`: an unverified quote, a paraphrase, a broken
    promise with no quote and no kept quote before)."""
    return [f for f in _new_findings(before_run, after_run)
            if _placement(f, before_run, diff) == UNPLACED]


def _finding_names(findings: list[Finding], n: int = 5) -> str:
    """`CODE vs source` for each of the first `n` findings (a broken
    promise's fact or brief field in place of the source)."""
    def against(f: Finding) -> str:
        return (f.fact_id or '?') if f.kind == 'broken-promise' else f.source
    return ', '.join(f'{f.code} vs {against(f)}' for f in findings[:n]) + (
        ' ...' if len(findings) > n else '')


def _persists(f: Finding, earlier: list[Finding]) -> bool:
    """Whether `f` is a problem the run before the fix already had: the same
    target (`checker.same_target`, a contradiction with no source only on a
    fact id both name): the same promise, or the same source and
    established words. The scene quote and code are not compared: the fix
    changed the one, and readings vary on the other. A contradiction with
    the same file or calendar but other established words (a fix that
    swaps one wrong date for another against another line) is a new one.

    `earlier` includes the run's inherited findings: a problem already in
    the book that the fix's words restate is that problem, not the fix's."""
    from storyforge.checker import same_target
    return any(same_target(f, g, need_fact=True) for g in earlier)


def _introduced(before_run: GateResult, after_run: GateResult, diff: _Diff) -> list[Finding]:
    """The blocking findings of `after_run` (the gate run on the fixed
    prose) that the fix brought in: new (`_new_findings`: not a problem
    `before_run` already had) and tied to the edits (`_placement`):

    - in words the fix changed (`EDITED`), or
    - a broken promise next to a change (`NEAR`; CR-2, #504's review).

    A new finding in words the fix left alone (`ALONE`) is not the fix's:
    two readings of the same words differ (E8, 2026-11-01). Nor is a
    broken promise whose words the run before found kept, unchanged by the
    fix (#737, aphrodite-drives-helen-to-bed: a question's answer flipped
    on them). Nor is a new finding that can't be placed (`UNPLACED`): it
    still counts in `_worse`'s total, and the caller is told it couldn't
    be placed."""
    if not after_run.check or not diff.after_spans:
        return []
    out = []
    for f in _new_findings(before_run, after_run):
        where = _placement(f, before_run, diff)
        if where == EDITED or (where == NEAR and f.kind == 'broken-promise'):
            out.append(f)
    return out


def _worse(n: int, before_run: GateResult, after_run: GateResult, diff: _Diff) -> str:
    """Why fix round `n`'s prose (which failed as `after_run`) is worse
    than the prose it fixed (failed as `before_run`), or '' when it isn't:
    more blocking problems, or a problem the fix brought in (`_introduced`).

    The count leaves out, on each side, the findings in words the fix left
    alone (`_in_untouched_text`; after the fix, `_placement` `ALONE`, which
    places a new broken promise with no quote by the words the run before
    found it kept): those words are in both proses, and two readings of
    them differ. E4's missing-persons (2026-11-03): a fix cleared both
    first findings, the re-check found four new ones, every one in words
    it hadn't touched, and a plain count would have thrown the fix away. A
    finding that can't be placed counts."""
    then_alone = sum(_in_untouched_text(f, diff, before=True)
                     for f in before_run.findings + before_run.unverified)
    # a finding the run before had is placed as it was counted there, by
    # its scene quote (#737's review SF-1); a new one may be placed by a
    # kept quote
    new = {id(f) for f in _new_findings(before_run, after_run)}
    now_alone = sum(_placement(f, before_run, diff, by_kept=id(f) in new) == ALONE
                    for f in after_run.findings + after_run.unverified)
    then = _blocking_count(before_run) - then_alone
    now = _blocking_count(after_run) - now_alone
    if now > then:
        alone = (f' (not counting {then_alone} and {now_alone} in words it left alone)'
                 if then_alone or now_alone else '')
        return f'fix round {n} left {now} problem(s), more than the {then} before it{alone}'
    new = _introduced(before_run, after_run, diff)
    if new:
        return (f'fix round {n} brought in {len(new)} problem(s) ('
                + '; '.join(_one_line(f.message())[:200] for f in new[:3])
                + (' ...' if len(new) > 3 else '') + ')')
    return ''


def _edit_span(prose_words: list[str], replace: str) -> list[Span]:
    """Where an edit's replacement lies in the fixed prose's words."""
    return _quote_spans(replace, prose_words) if _word_list(replace) else []


def _bad_edits(edits: list[dict], new: list[Finding], diff: '_Diff',
               before_run: GateResult | None = None) -> list[int] | None:
    """The indexes of `edits` that brought in `new` (`_introduced`'s
    findings), or None when one can't be tied to an edit: a finding whose
    scene quote lies in or next to an edit's replacement, a broken promise
    whose kept words (`_kept_places`, in the prose before the fix) lie in
    an edit's `find` (or, when none holds them, next to one), or one whose
    promised words the edit took out (its `find` shares four words in a
    row with them)."""
    after_words = diff.after
    bad: set[int] = set()
    for f in new:
        hit = set()
        places = _quote_spans(f.scene_quote, after_words) if f.scene_quote else []
        kept = [] if places else _kept_places(f, before_run, diff.before)
        finds = [_edit_span(diff.before, e.get('find') or '') for e in edits]
        # the edits whose `find` held the kept words, else those next to
        # them, as `_placement` reads them (#737's review CR-1)
        in_kept = {i for i, sp in enumerate(finds) if any(_touches(p, sp) for p in kept)}
        by_kept = in_kept or {i for i, sp in enumerate(finds)
                              if any(_touches(p, sp, near=True) for p in kept)}
        for i, e in enumerate(edits):
            spans = _edit_span(after_words, e.get('replace') or '')
            if places and any(_touches(p, spans, near=True) for p in places):
                hit.add(i)
            elif i in by_kept:
                hit.add(i)
            elif (f.kind == 'broken-promise' and f.established_quote
                  and _shares_run(_words(e.get('find') or ''), _words(f.established_quote))):
                hit.add(i)
        if not hit:
            return None
        bad |= hit
    return sorted(bad)


def _shares_run(a: str, b: str, n: int = 4) -> bool:
    """Whether two `_words` strings share a run of `n` words."""
    aw, bw = a.split(), b.split()
    runs = {tuple(aw[i:i + n]) for i in range(len(aw) - n + 1)}
    return any(tuple(bw[i:i + n]) in runs for i in range(len(bw) - n + 1))


def _partial_fix(project_dir: str, scene_id: str, command: str, current: str,
                 before_run: GateResult, after_run: GateResult, diff: '_Diff',
                 edits: list[dict], *, log_dir: str, extract_model, check_model,
                 before) -> tuple[list[dict], str, GateResult, str, list[str]] | None:
    """B-030 (#556): a fix round with several edits, discarded because it
    brought in problems, is retried with only the edits that didn't
    (`_bad_edits`), one more gate run. Returns (the edits kept, their
    prose, its gate run, the dropped edits as text, notes naming its run's
    new findings that couldn't be placed or lie in words the edits left
    alone, `_round_notes`; #737's review SF-3), or None when every
    edit (or none) is to blame, a new problem can't be tied to one, the
    rest can't be applied, the run fails, or it is worse than `before_run`
    (`_worse`)."""
    if len(edits) < 2:
        return None
    new = _introduced(before_run, after_run, diff)
    if not new:
        return None   # worse by count alone: nothing to tie to an edit
    bad = _bad_edits(edits, new, diff, before_run)
    if not bad or len(bad) == len(edits):
        return None
    good = [e for i, e in enumerate(edits) if i not in bad]
    try:
        prose = apply_edits(current, good)
        run = gate_scene(project_dir, scene_id, command=command, prose=prose,
                         log_dir=log_dir, extract_model=extract_model,
                         check_model=check_model, before=before, carry=before_run,
                         open_from=before_run)
    except GateError:
        return None
    notes: list[str] = []
    if not run.passed:
        d = _diff(current, prose)
        if _worse(0, before_run, run, d):
            return None
        loose, alone = _round_notes('the edits kept', before_run, run, d)
        notes = [n for n in (loose, alone and f'{alone}: not the fix\'s, so they stand for the '
                             f'next round or the author') if n]
    dropped = '; '.join(f'"{_one_line(edits[i].get("find", ""))[:60]}"' for i in bad)
    return good, prose, run, dropped, notes


def _round_notes(what: str, before_run: GateResult, after_run: GateResult,
                 diff: '_Diff') -> tuple[str, str]:
    """What the notes say of `after_run`'s new findings (`what`: the fix
    round it checked): those that couldn't be placed relative to the fix,
    judged by the count (SF-3, #504's review), and the start of the line
    naming those in words it left alone (#737), each '' when there are
    none."""
    unplaced = _unplaced(before_run, after_run, diff)
    loose = (f'{what}: {len(unplaced)} new finding(s) of the check after it could not be '
             f'placed in the fixed prose (' + _finding_names(unplaced)
             + '): judged by the problem count only') if unplaced else ''
    alone = _alone(before_run, after_run, diff)
    found = (f'{what}: {len(alone)} new finding(s) of the check after it in words the fix '
             f'left alone (' + _finding_names(alone) + ')') if alone else ''
    return loose, found


def run_log_dir(log_dir: str, scene_id: str, *, now=None, pid: int | None = None) -> str:
    """A new directory, created, for one gate invocation's logs of
    `scene_id`: `log_dir/<scene>/<YYYYMMDD-HHMMSS>-<pid>`, with `-2`, `-3`
    ... when that is taken. Callers pass a fixed `log_dir` (write's
    working/logs/gate, check's working/logs/check), and the log files are
    named by scene alone (gate-check-<scene>.json), so without it a later
    run of the scene, or a re-check of it in the same run, overwrote the
    record of what the earlier one was told and changed.

    The directory is made exclusively (`os.mkdir`), so two calls never share
    one, whatever the clock. `now` (a datetime) and `pid` are for tests.

    Raises:
        GateError: the directory can't be made (SF-5, #504's review: a
            traceback named nothing); nothing was run.
    """
    from datetime import datetime
    stamp = f'{(now or datetime.now()):%Y%m%d-%H%M%S}-{os.getpid() if pid is None else pid}'
    parent = os.path.join(log_dir, scene_id)
    base = os.path.join(parent, stamp)
    path, n = base, 1
    try:
        os.makedirs(parent, exist_ok=True)
        while True:
            try:
                os.mkdir(path)
                return path
            except FileExistsError:
                n += 1
                path = f'{base}-{n}'
    except OSError as e:
        raise GateError(f'{scene_id}: can\'t make the gate log directory {path}: {e}') from e


def gate_and_fix(project_dir: str, scene_id: str, *, command: str, prose: str,
                 log_dir: str, extract_model: str | None = None,
                 check_model: str | None = None, fix_model: str | None = None,
                 before: Snapshot | None = None, fixer: Fixer | None = None) -> GatedScene:
    """Gate `prose`; while it doesn't pass, fix it and gate the fixed prose,
    at most `FIX_ROUNDS` times (plan §3.2 step 3). Each fix after the first is
    sent the earlier fixes' problems and edits (`rounds`, `build_fix_prompt`).

    - A first run with nothing for the fix (`problems_to_fix` empty: it
      failed on extraction problems, which aren't sent to the fix) and no
      plan conflicts is re-gated without an edit, so extraction runs again.
      That re-roll counts as a round and logs to `recheck/`.
    - A later run with nothing for the fix stops, unless all that stopped
      it is the extractor's slips (`_only_extractor_slips`: a quote not in
      the prose or none, with no halt, other extraction problem, finding,
      plan conflict or unverified finding; #598). Then the
      same prose is gated again (`_reextract`: extraction and the check;
      logged; in `reextract/`; not a round), and so is the last round's
      re-check when only slips stopped it. That is at most once per
      invocation (`_OneRegate`), round 1's re-roll included: a first run
      failing on slips alone is extracted twice, not three times. What the
      re-extraction's run finds instead goes to the next round's fix while
      one is left; after the last round it is the verdict. That run holds
      back each fact it misquotes again (`gate_scene(hold_slips=True)`,
      `_hold_slips`: not recorded, a NOTE, not a stop; never fuzzy-matched
      to the prose's words: one word can change the fact); one that can't
      finish keeps the run before it.
    - A run with real problems beside slips goes to the fix, not a
      re-extraction: the fix's re-check extracts the edited prose anyway.
      The run the loop ends on, though, is extracted again when its slips
      stand beside the check's findings alone (`_slips_beside_findings`:
      no halt, other extraction problem or plan conflict;
      #734, diomedes-spears-ares: a slip beside a possession finding
      stopped a provisional commit, and the session), once, as above, with
      those findings standing in the new run (`_reextract(standing=True)`),
      so a re-roll of the check can't pass the prose.
    - A run with plan conflicts and nothing for the fix (extraction problems
      or not) is neither fixed nor re-gated: they are the author's (the brief
      disagrees with the book), and a re-roll that missed one would pass
      prose that has it.
    - `before` (the book before the pass, `snapshot`) goes to every run
      (`gate_scene`): an inherited contradiction doesn't block any of them.
    - A fix that changes nothing (every problem judged a false alarm) is not
      re-gated: the last verdict stands, and a re-roll of the same prose
      won't overturn it.
    - Every round, the first included: a fix whose run fails worse than
      the run before it (`_worse`: more blocking problems near the change,
      or a problem it brought in, `_introduced`) is discarded (mended-bridle,
      2026-11-03: the first fix made a scene that agreed with its brief
      match a later scene's error, and its re-check, fewer problems in all,
      was kept). The prose and verdict before it are kept, `BLOCKED_PATH`
      is put back to that run's contradictions (`.blocked_stale` when it
      can't be), and `.discarded` names the round. A first fix discarded
      leaves the prose as given (`.fixed` False). A run that passed is
      always kept (it committed), and so is a re-gate with no edit (the
      same prose). A new finding in words the fix left alone (#737: a
      question's answer flipping on unchanged prose) doesn't make a fix
      worse: it stands in the run kept, for the next round or the author.
    - Round 2 on: the fix is also discarded, the earlier prose and verdict
      kept, when the fix or its check fails (`GateError`; in round 1 that
      raises, there being no fixed prose to keep) or it puts back words an
      earlier fix removed (checked before its gate run, which would commit
      on a lucky pass).
    - Each discard, each round's new findings it couldn't place, and each
      kept round's new findings in words it left alone, is in `.notes` for
      the caller to log.
    - Otherwise the prose kept is the last gated, with that run's verdict.

    The caller must write `.prose` to the scene file at once, whether or not
    `.result.passed`: when it passed, the ledger was already committed with
    quotes from that prose.

    `fixer` replaces `fix_scene` (`Fixer`'s contract). A writing session
    passes one that sends the problems to the writer that wrote the scene
    (#655), so every rule above holds for its fixes too; its fix turns are
    logged in the session's folder, and copied to this run's log folder.

    Raises:
        GateError: from the first gate run, the first fix or its re-gate; it
            carries the first run as `.first` (None when the first run itself
            failed), so its findings can still be reported, and the logs as
            `.log_dir`.

    Logs: each invocation writes to its own `run_log_dir(log_dir,
    scene_id)` (`.log_dir`), so a later gate of the scene never overwrites
    this one's.
    """
    from storyforge import api
    logs = run_log_dir(log_dir, scene_id)
    first = None
    try:
        first = gate_scene(project_dir, scene_id, command=command, prose=prose, log_dir=logs,
                           extract_model=extract_model, check_model=check_model,
                           before=before)
        current, result, rounds, notes, run_dir = prose, first, [], [], logs
        discarded, blocked_stale, unseen = 0, '', 0
        regate, reextraction = _OneRegate(), None
        for n in range(1, FIX_ROUNDS + 1):
            if result.passed:
                break
            if n > 1 and _only_extractor_slips(result) and regate.take():
                result, run_dir, reextraction = _reextract(
                    project_dir, scene_id, command, current, result, logs,
                    extract_model=extract_model, check_model=check_model, before=before,
                    fallback_dir=run_dir)
                if result.passed:
                    break
            to_fix = problems_to_fix(result)
            if not to_fix and (result.plan_conflicts or n > 1
                               or any(h.planned for h in result.halts)):
                break
            # round 1 with nothing for the fix: re-gate the same prose
            misquoted = None
            if not to_fix:
                regate.take()   # the first take: always granted
                if _only_extractor_slips(result):
                    misquoted = result
                    _say_misquoted(scene_id, result)
            kept = ('the prose as given and the first verdict' if n == 1
                    else 'the prose and verdict before it')
            # the brief's own words the scene has: the fix must keep them
            protected = [p for p in _brief_phrases(project_dir, scene_id)
                         if _quoted_in(p, current)]
            edits: list[dict] = []
            try:
                with api.metered() as meter:
                    try:
                        fixed = (fixer or fix_scene)(
                            scene_id, current, result, log_dir=run_dir, model=fix_model,
                            protected=protected, earlier=tuple(rounds), edits_out=edits)
                    finally:
                        _log_spend(meter, project_dir, 'gate-fix', scene_id)
            except GateError as e:
                if n == 1:
                    raise
                notes.append(f'fix round {n} failed ({e}); kept {kept}')
                discarded = n
                break
            if to_fix and fixed == current:
                break
            undone = _undone_edit(rounds, current, fixed) if n > 1 else None
            if undone:
                notes.append(f'fix round {n} put back words an earlier fix removed '
                             f'("{_one_line(undone)[:80]}"); kept {kept}')
                discarded = n
                break
            # each run's log (and the fix that read it) in its own directory:
            # logs, logs/recheck, logs/recheck-2
            next_dir = os.path.join(logs, 'recheck' if n == 1 else f'recheck-{n}')
            try:
                # #736: a fix's re-check carries the facts of the run before
                # it (`_carry_of`); a re-gate of the same prose (nothing to
                # fix) is there to read them again. #738: under tandem
                # neither makes an open reading; the run before's stands
                again = gate_scene(project_dir, scene_id, command=command, prose=fixed,
                                   log_dir=next_dir, extract_model=extract_model,
                                   check_model=check_model, before=before,
                                   carry=result if to_fix else None, open_from=result,
                                   hold_slips=misquoted is not None)
            except GateError as e:
                if n == 1:
                    raise
                what = ('the ledger write after fix round {n} was refused'
                        if isinstance(e, LedgerWriteRefused)
                        else 'the check after fix round {n} failed').format(n=n)
                notes.append(f'{what} ({e}); kept {kept}')
                discarded = n
                break
            if misquoted is not None:
                reextraction = Reextraction.of(misquoted, again)
            # never worse, the first round included (mended-bridle, 2026-11-03:
            # round 1 made a correct scene match another scene's error, and its
            # re-check's broken promise, in the words it changed, was kept).
            # A pass is kept: it committed. A re-roll with no edit is the
            # same prose, so its verdict stands
            worse, loose, found = '', '', ''
            if fixed != current and not again.passed:
                diff = _diff(current, fixed)
                worse = _worse(n, result, again, diff)
                # SF-3 (#504's review): a new problem that can't be placed is
                # neither tied to the fix nor cleared of it; #737: one in
                # words the fix left alone is the prose's, not the fix's
                # (`_worse` leaves it out). Both said below
                loose, found = _round_notes(f'fix round {n}', result, again, diff)
            if worse:
                # B-030 (#556): keep the edits that didn't do it
                part = _partial_fix(project_dir, scene_id, command, current, result, again,
                                    diff, edits, log_dir=os.path.join(logs, f'partial-{n}'),
                                    extract_model=extract_model, check_model=check_model,
                                    before=before)
                if part is not None:
                    good, part_prose, part_run, dropped_edits, part_notes = part
                    notes.append(f'{worse}; kept its {len(good)} edit(s) that did not, '
                                 f'dropped {dropped_edits}, and re-checked')
                    # #737's review SF-2, CR-4: this run is set aside, and
                    # the re-check of the edits kept read its words again
                    if loose:
                        notes.append(loose)
                    if found:
                        notes.append(f'{found}: not the fix\'s; the re-check of the edits kept '
                                     f'read those words again')
                    notes += part_notes
                    rounds.append(FixRound(to_fix, good))
                    current, result, run_dir = part_prose, part_run, os.path.join(
                        logs, f'partial-{n}')
                    if part_run.passed:
                        break
                    continue
                notes.append(f'{worse}; kept {kept}')
                discarded = n
                if loose:
                    notes.append(loose)
                if found:
                    # in the prose kept too, but not in the verdict kept
                    notes.append(f'{found}: in the prose kept too, but not in the verdict '
                                 f'kept; a re-check of the scene reads them again')
                    unseen = len(_alone(result, again, diff))
                # the blocked list is the kept run's, for `check --accept`
                blocked_stale = _note_blocked(project_dir, scene_id, command, result)
                # and so is the advisory list (#642)
                _note_advisory(project_dir, scene_id, command, result, prose=current)
                if blocked_stale:
                    notes.append(f'WARNING: {blocked_stale}; it lists the discarded fix\'s '
                                 f'contradictions, which `check --accept` refuses')
                break
            if loose:
                notes.append(loose)
            if found:
                notes.append(f'{found}: not the fix\'s, so they stand for the next round or '
                             f'the author')
            if fixed != current:
                rounds.append(FixRound(to_fix, edits))
            current, result, run_dir = fixed, again, next_dir
        # the run kept failed on the extractor's slips, alone or beside the
        # check's findings (#734: no fix repairs a slip, and one stops a
        # provisional commit): extract the same prose again, its findings
        # standing
        if _slips_beside_findings(result) and regate.take():
            result, run_dir, reextraction = _reextract(
                project_dir, scene_id, command, current, result, logs,
                extract_model=extract_model, check_model=check_model, before=before,
                fallback_dir=run_dir, standing=True)
    except GateError as e:
        e.first, e.log_dir = first, logs
        raise
    return GatedScene(current, result, first, fixed=current != prose, rounds=rounds,
                      notes=notes, log_dir=logs, discarded=discarded, unseen=unseen,
                      blocked_stale=blocked_stale, reextraction=reextraction)


#: Extraction problems that are the extractor's own slip, never the prose's:
#: a quote that isn't in the scene (`extract.commitment_rows` checks it
#: against the prose), no quote at all, or a `supersedes` or `ends` naming
#: no fact in force (#634: an id it made up, or one it can't tell apart).
#: No prose edit repairs one, so the fix is never sent them
#: (`problems_to_fix`), and they earn the one re-extraction
_EXTRACTOR_SLIPS = (MISQUOTE, NO_QUOTE, 'supersedes', 'ends')


#: The extractor's quote slips: a quote not in the scene, or none.
#: Held back on a reading again of the same prose (`_hold_slips`)
_QUOTE_SLIPS = (MISQUOTE, NO_QUOTE)


def _hold_slips(result: GateResult) -> None:
    """On a reading again of prose an earlier run stopped on the
    extractor's quote slips (`gate_scene(hold_slips=True)`): take each fact
    this reading misquoted, or gave no quote, out of `proposed` (and
    `claims`), with the ends it carries, and out of `problems`, into
    `slips_held`, reported as a NOTE (`report_lines`, `applied_lines`). The
    scene is not stopped for them: a quote slip is the gate's own
    extraction's, which no prose edit repairs, and the retry has been had
    (E4's re-record, #784: `waking-hank`, `waking-maren` and
    `missing-persons` stopped on the same slip read twice, "she had" for
    the prose's "she'd had", "had not" for "hadn't", "knows" for "knew").
    Nothing is recorded on words the scene doesn't have, and the quote is
    never replaced with the prose's words (#598: one word can change the
    fact), so the fact is not in the ledger and later scenes aren't checked
    against it; the NOTE says so. Everything else the reading found stands:
    a halt or dispute the slipped fact raised was taken before this, and
    still stops the scene."""
    ids = {item.split(': ', 1)[-1] for kind in _QUOTE_SLIPS
           for item in result.problems.get(kind, [])}
    if not ids:
        return
    result.slips_held = [s for s in _describe_slips(result)
                         if s.split(': ', 1)[0] in ids]
    result.proposed = [r for r in result.proposed if r['id'] not in ids]
    result.claims = [r for r in result.claims if r['id'] not in ids]
    result.ends = [e for e in result.ends if (e.carrier or {}).get('id') not in ids]
    for kind in _QUOTE_SLIPS:
        result.problems[kind] = []


def _held_slips_line(result: GateResult) -> list[str]:
    """The NOTE line for `result.slips_held` ([] when none)."""
    if not result.slips_held:
        return []
    return [f'NOTE (not recorded: extraction misquoted these again on reading the same prose '
            f'a second time; the scene is not stopped for its own extraction\'s slip, and '
            f'later scenes are not checked against these facts): '
            + _one_line('; '.join(result.slips_held))]


class _OneRegate:
    """The one gate run of unchanged prose a `gate_and_fix` call may make for
    its extraction (#598): round 1's re-roll or `_reextract`. `take()`
    claims it: True the first time, False after; `taken` says whether it
    was."""

    def __init__(self) -> None:
        self.taken = False

    def take(self) -> bool:
        if self.taken:
            return False
        self.taken = True
        return True


def _only_extractor_slips(result: GateResult) -> list[str]:
    """The extractor's slips (`_EXTRACTOR_SLIPS`, as `unresolved` lists
    them) when they are all that stopped `result`; [] when it passed or
    anything else blocks (a halt, another extraction problem, a finding, a
    plan conflict, an unverified finding; an unruled dispute is advisory and
    doesn't count)."""
    if result.passed or result.halts or result.findings or result.unverified:
        return []
    if any(result.problems.get(k) for k in UNRESOLVED if k not in _EXTRACTOR_SLIPS):
        return []
    return [f'{k}: {item}' for k in _EXTRACTOR_SLIPS for item in result.problems.get(k, [])]


def _slips_beside_findings(result: GateResult) -> list[str]:
    """#734: the extractor's slips (as `_only_extractor_slips` lists them)
    when the rest of what stopped `result` is the check's findings,
    verified or not, none a plan conflict; [] when it passed or has no slip,
    or a halt, another extraction problem or a plan conflict stopped it (an
    unruled dispute is advisory and doesn't count). No prose edit repairs a
    slip, and a slip stops a
    provisional commit (`can_commit_provisionally`), so a run ending a fix
    loop with findings and a slip is extracted again (`gate_and_fix`), the
    findings standing (`_carry_standing`). diomedes-spears-ares (iliad-adult,
    2026-11-16): an `ends` slip beside a possession finding halted the
    session with 73 scenes not attempted."""
    if result.passed or result.halts or result.plan_conflicts:
        return []
    if any(result.problems.get(k) for k in UNRESOLVED if k not in _EXTRACTOR_SLIPS):
        return []
    return [f'{k}: {item}' for k in _EXTRACTOR_SLIPS for item in result.problems.get(k, [])]


def _carry_standing(check: CheckResult, run: GateResult,
                    disputes: list[Dispute] = ()) -> None:
    """#734: `run`'s blocking findings, verified and unverified, added to
    `check` (a run of the same prose) unless it made one again
    (`_persists`): a re-extraction re-reads the facts, and a re-roll of the
    check that missed a finding must not pass the prose. A finding that was
    the ruling on one of `run`'s disputes (a plan fact extraction said the
    scene changes) stands only while this run's extraction still raises
    that dispute (`disputes`; #734's review CR-4): the reading it ruled on
    is gone."""
    gone = ({d.fact_id for d in _disputes(run, [])}
            - {d.fact_id for d in disputes})

    def stands(f: Finding) -> bool:
        return not (f.fact_id in gone and not f.established_scene)
    have = check.findings + check.unverified
    check.findings.extend(f for f in run.findings if stands(f) and not _persists(f, have))
    check.unverified.extend(f for f in run.unverified
                            if stands(f) and not _persists(f, have))


#: How much of a misquoted quote a log line or pending reason shows
_SLIP_QUOTE_CHARS = 60
#: How many slips one line names before "and N more"
_SLIPS_SHOWN = 3


def _describe_slips(result: GateResult) -> list[str]:
    """Each of `result`'s extractor slips as `fact-id: what`: the quote
    (cut to `_SLIP_QUOTE_CHARS`) that isn't in the scene, or "no quote";
    a link's as `supersedes|ends id: names no fact in force` (#634)."""
    proposed = {r['id']: r for r in result.proposed}
    out = []
    for kind in _EXTRACTOR_SLIPS:
        for item in result.problems.get(kind, []):
            rid = item.split(': ', 1)[-1]
            if kind not in (MISQUOTE, NO_QUOTE):
                out.append(f'{kind} {_one_line(rid)}: names no fact in force')
                continue
            if kind == NO_QUOTE:
                out.append(f'{rid}: no quote')
                continue
            quote = _one_line(proposed.get(rid, {}).get('quote', ''))
            if len(quote) > _SLIP_QUOTE_CHARS:
                quote = quote[:_SLIP_QUOTE_CHARS].rstrip() + '…'
            out.append(f'{rid}: "{quote}" is not in the scene' if quote
                       else f'{rid}: its quote is not in the scene')
    return out


def _slip_text(slips: list[str]) -> str:
    shown = '; '.join(slips[:_SLIPS_SHOWN])
    return shown + (f'; and {len(slips) - _SLIPS_SHOWN} more' if len(slips) > _SLIPS_SHOWN
                    else '')


def _slipped(slips: list[str]) -> str:
    """What the extractor did, for `slips` (`_describe_slips`): misquoted
    the prose, named a fact not in force (#634), or both."""
    links = sum(s.endswith(': names no fact in force') for s in slips)
    if not links:
        return 'misquoted the prose'
    return ('named a fact not in force' if links == len(slips)
            else 'misquoted the prose or named a fact not in force')


def _say_misquoted(scene_id: str, run: GateResult) -> None:
    """The log line for a gate run of the same prose after the extractor
    misquoted it (#598) or named a fact not in force (#634): which facts,
    and what it quoted."""
    from storyforge.common import log
    slips = _describe_slips(run)
    log(f'  {scene_id}: the extractor {_slipped(slips)} ({_slip_text(slips)}); '
        f'gating the same prose again (extraction and the check), not sending it to the fix')


def _reextract(project_dir: str, scene_id: str, command: str, prose: str | None,
               run: GateResult, logs: str, *, extract_model: str | None,
               check_model: str | None, before: Snapshot | None,
               fallback_dir: str, introduced_by: str | None = None,
               catch_all: bool = True,
               standing: bool = False) -> tuple[GateResult, str, Reextraction]:
    """#598 (Telemachy, 2026-11-05): a re-check after a fix failed only on a
    quote the extractor changed ("she would sit" for the prose's "he would
    sit"); the fix edits prose, so it had nothing to do, and `write
    --keep-going` stopped (`can_commit_provisionally`: a commit would write
    the wrong quote). Gate the same `prose` again with `gate_scene`: the
    whole run, extraction and every reading of the check (its spend is a
    `gate` row like any run's), not extraction alone, so the check rules on
    the new extraction's disputes. Return that run and its log directory
    (`logs/reextract`) and how it came out (`Reextraction`, which the
    caller reports). The quote is never replaced by the prose's words: one
    word (he/she) can change the fact.

    The run that comes back is kept, a verdict on the same prose, read
    with `hold_slips`: a fact it misquotes again is held back, not
    recorded and not a stop (`_hold_slips`; both runs' slips are in the
    `Reextraction`); a pass has committed; one stopped by a link slip
    alone again has it reported; one stopped by anything
    else (a finding this check makes, or a halt or other problem the new
    extraction brings) goes to the next round's fix while `gate_and_fix`
    has one left, and after the last round is the verdict. A run that
    raises keeps `run` and `fallback_dir` (`REGATE_ERROR`, naming the
    error): `GateError`, or any other exception (#602's review SF-5: one
    escaping here lost the fix rounds' edits to write's catch-all, which
    keeps the prose as drafted). The prose is unchanged, so the run before
    is still its verdict.

    From `gate_unchanged` (a re-check, `storyforge check`) there is no fix:
    `prose` is None (the scene file), `introduced_by` is passed on, the run
    that comes back is the verdict, and `catch_all` is off: no edits are at
    stake, so an exception other than `GateError` (a bug, not the
    extractor's) propagates with its traceback.

    With `standing` (#734: `gate_and_fix`'s last run, whose slips stood
    beside the check's findings), `run`'s findings stand in the new run
    (`gate_scene(standing=)`): it can't pass on a re-roll of the check that
    missed one, and the `Reextraction` counts them."""
    _say_misquoted(scene_id, run)
    run_dir = os.path.join(logs, 'reextract')
    kept = len(run.findings) + len(run.unverified) if standing else 0
    try:
        again = gate_scene(project_dir, scene_id, command=command, prose=prose,
                           log_dir=run_dir, extract_model=extract_model,
                           check_model=check_model, before=before,
                           introduced_by=introduced_by,
                           standing=run if kept else None, open_from=run,
                           hold_slips=True)
    except GateError as e:
        return run, fallback_dir, Reextraction.of(run, error=str(e))
    except Exception as e:   # a bug or an I/O failure: say it, keep the fixes
        if not catch_all:
            raise
        return run, fallback_dir, Reextraction.of(run, error=f'{type(e).__name__}: {e}')
    reextraction = Reextraction.of(run, again)
    reextraction.standing = kept
    return again, run_dir, reextraction


def _read_blocking(project_dir: str, scene_id: str, prose: str, check_model: str | None,
                   log_dir: str, result: 'GateResult'):
    """The scene's blocking, by `GATE_BLOCKING_METHOD`: the blocking read
    on the checker's model, or the stage sheet on its own small model
    (#647), whose sheet is saved for the next scene to carry over and whose
    notes (what it couldn't check) go to `result.stage_notes`, logged and
    reported. Either failing is a `GateError`."""
    if GATE_BLOCKING_METHOD not in BLOCKING_METHODS:
        raise GateError(f'GATE_BLOCKING_METHOD is {GATE_BLOCKING_METHOD!r}, not one of '
                        f'{", ".join(BLOCKING_METHODS)}')
    if GATE_BLOCKING_METHOD == 'stage-sheet':
        from storyforge.stage_sheet import StageSheetError, check_stage_sheet
        from storyforge.world_table import WorldTableError
        try:
            sheet = check_stage_sheet(project_dir, scene_id, prose=prose, save=True,
                                      log_file=os.path.join(log_dir,
                                                            f'gate-stage-{scene_id}.json'))
        except (StageSheetError, WorldTableError) as e:
            raise GateError(str(e)) from e
        result.stage_notes = list(sheet.notes)
        if sheet.notes:
            from storyforge.common import log
            log(f'  {scene_id}: stage sheet, not checked: {"; ".join(sheet.notes)}')
        return sheet
    try:
        return check_blocking(project_dir, scene_id, prose=prose, model=check_model,
                              log_file=os.path.join(log_dir, f'gate-blocking-{scene_id}.json'))
    except BlockingError as e:
        raise GateError(str(e)) from e


def _read_continuity(project_dir: str, scene_id: str, prose: str, rows: list[dict[str, str]],
                     log_dir: str):
    """The continuity checks' model call (#648): the scene's typed state,
    read against the ledger without its earlier commitments (`rows`, as the
    checker reads it), and saved. It writes nothing of the gate's result,
    so it can run beside extraction and the blocking read; `_merge_continuity`
    takes in what it found. A failure is a `GateError`: the scene can't be
    checked."""
    from storyforge.continuity import ContinuityError, check_continuity
    try:
        return check_continuity(project_dir, scene_id, prose=prose, rows=rows,
                                log_file=os.path.join(log_dir, f'gate-state-{scene_id}.json'))
    except ContinuityError as e:
        raise GateError(str(e)) from e


def _merge_continuity(scene_id: str, got, result: 'GateResult') -> list:
    """The continuity checks' findings join the check's (a finding on the
    same words with the same code as one the check or the blocking read
    already made is left out, so one slip isn't two; for the sun, also a
    stage sheet's BLK on those words), their notes go to
    `result.state_notes`, logged and reported. Returns the typed state's
    records (the question layer's cast, #649)."""
    from storyforge.common import log
    from storyforge.continuity import overlaps
    have = result.check.findings + result.check.unverified
    for f in got.findings:
        # the stage sheet checks the sun too (#647): its BLK on these words is this slip
        same = (f.code, BLOCKING_CODE) if f.explanation.startswith('(typed state, sky)') \
            else (f.code,)
        if not any(g.code in same and overlaps(g.scene_quote, f.scene_quote) for g in have):
            result.check.findings.append(f)
    result.state_notes = list(got.notes)
    if got.notes:
        log(f'  {scene_id}: continuity, not checked or advisory: {"; ".join(got.notes)}')
    return got.records


def _check_continuity(project_dir: str, scene_id: str, prose: str, rows: list[dict[str, str]],
                      log_dir: str, result: 'GateResult') -> list:
    """`_read_continuity` then `_merge_continuity`, one after the other."""
    return _merge_continuity(scene_id, _read_continuity(project_dir, scene_id, prose, rows,
                                                        log_dir), result)


#: What the question layer doesn't do that the open checker did (#649): a
#: NOTE on every scene it checks, so a pass doesn't read as more than it is.
#: It asks about ledger facts and the brief; the open checker reads the book
QUESTION_LAYER_GAPS = (
    'contradictions with earlier prose that no ledger fact records, and with the reference '
    'bibles and the calendar, were not looked for (the questions ask only about ledger '
    'facts and the brief; the open checker reads the book)',
)


#: #738: what a tandem re-check doesn't do, beside the questions' notes:
#: the open checker read the prose before the fix, not the words it put in
TANDEM_RECHECK_GAP = (
    'the words the fix put in were not read by the open checker: contradictions there with '
    'earlier prose that no ledger fact records, and with the reference bibles and the '
    'calendar, were not looked for (the open checker read the scene\'s first run; its '
    'findings there stand where the fix left their words alone, are dropped where it took '
    'their words out, and were asked again where it changed words next to them)')
#: #738: `_ask_questions(tandem=)`: beside the open checker's own reading
#: (a first run) or the findings carried from it (a re-check)
READ, CARRIED = 'read', 'carried'
#: #738: why an open finding carried into a re-check is unverified: the
#: fix changed its words, the scene was found to have it still, and no
#: asking gave words of the fixed prose that have it
CARRIED_UNPLACED = ('found by the open checker on the prose before the fix and still there '
                    'by the re-check\'s asking, which gave no words of the fixed prose for it')


def _from_open(f: Finding) -> bool:
    return f.checker in (OPEN, BOTH)


@dataclass
class OpenRulings:
    """#738: the open checker's rulings in a tandem run, by fact id, for a
    re-check to carry: the disputes and endings it was asked (each with
    the claim extraction read, `Dispute.claim`, whose words place it in the
    prose), which disputes it cleared and which endings it found the scene
    shows. A dispute it ruled a contradiction is a finding
    (`GateResult.open_findings`), carried as findings are."""
    disputes: dict[str, str] = field(default_factory=dict)
    cleared: set[str] = field(default_factory=set)
    endings: dict[str, str] = field(default_factory=dict)
    ended: set[str] = field(default_factory=set)

    @classmethod
    def of(cls, check: CheckResult, disputes: list[Dispute],
           endings: list[Dispute]) -> 'OpenRulings':
        """The open checker's own reading's rulings (`check`, before the
        question layer joins it)."""
        return cls({d.fact_id: d.claim for d in disputes}, {d.fact_id for d in check.cleared},
                   {d.fact_id: d.claim for d in endings}, {d.fact_id for d in check.ended})


def _words_untouched(text: str, diff: '_Diff | None') -> bool:
    """#738: whether `text` lies in words the fix left alone, in the prose
    before it (`_place` `ALONE`); always on the same prose (`diff` None).
    Words not found there can't be shown untouched: no."""
    if diff is None:
        return True
    return bool(text.strip()) and _place(*_side(text, diff, before=True)) == ALONE


def _carry_rulings(run: 'GateResult', disputes: list[Dispute], endings: list[Dispute],
                   diff: '_Diff | None', result: 'GateResult') -> None:
    """#738: the open checker's first-run rulings (`run.open_rulings`) a
    re-check keeps: each on a dispute or ending this run asks again with
    the same claim, whose words the fix left alone (`_words_untouched`).
    One asked again whose words the fix changed (or whose claim changed)
    is not carried, and the notes say so; the questions alone rule it.
    The kept ones are this run's `open_rulings`, for the next."""
    view = run.open_rulings or OpenRulings()
    out = OpenRulings()
    lost = []
    for kind, asked, ruled, now in (('dispute', view.disputes, view.cleared, disputes),
                                    ('ending', view.endings, view.ended, endings)):
        for d in now:
            if d.fact_id not in asked:
                continue
            claim = asked[d.fact_id]
            if claim == d.claim and _words_untouched(claim, diff):
                (out.disputes if kind == 'dispute' else out.endings)[d.fact_id] = claim
                if d.fact_id in ruled:
                    (out.cleared if kind == 'dispute' else out.ended).add(d.fact_id)
            else:
                lost.append(f'{kind} on {d.fact_id}')
    result.open_rulings = out
    if lost:
        result.check_notes.append(
            f'the open checker\'s first-run ruling on {len(lost)} item(s) not carried, the '
            f'fix changed the words it ruled on (the questions alone rule them): '
            + ', '.join(lost))


#: Why `_carry_open` drops a carried open finding without asking
TOOK_OUT = 'the fix took out the words they were found on'


def _took_out(f: Finding, diff: '_Diff') -> bool:
    """Whether the fix took out `f`'s words: a contradiction whose scene
    quote's words (`_quote_spans`, by words as the fix's diff reads them, so
    an edit to punctuation alone takes nothing out; #783's review ID-1) are
    in the prose before the fix and not after it. A broken promise (no
    words of its own) or a quote that wasn't in the prose before either
    can't be told so, and is asked again. One word of the quote changed
    is enough: the finding was read on words that are gone (#783's review
    ID-2: a rewording that keeps the slip passes this re-check unless the
    question layer or the blocking read finds it)."""
    return (f.kind != 'broken-promise' and bool(f.scene_quote.strip())
            and bool(_quote_spans(f.scene_quote, diff.before))
            and not _quote_spans(f.scene_quote, diff.after))


def _carry_open(scene_id: str, prose: str, run: 'GateResult', disputes: list[Dispute],
                log_dir: str, result: 'GateResult', endings: list[Dispute] = ()) -> None:
    """#738: a tandem run that makes no open reading carries `run`'s open
    findings (`open_findings`, on `open_prose`) into its check, where the
    open reading would have put them (before the shared layers' findings,
    so a continuity finding on the same words is one slip, not two). One
    whose scene quote lies in words the fix left alone (`_in_untouched_text`,
    on the prose before it; all of them, on the same prose) stands as it was
    (`UNTOUCHED`). One whose scene quote was in the prose before the fix and
    is gone from this prose is dropped (`TOOK_OUT`), named in `check_notes`:
    the fix took out the words it was found on, and an asking would read
    the new prose against the old explanation (E4 run 3, `pewter-town`,
    2026-11-27: a calendar finding re-anchored by an asking on words the
    fix wrote, then carried untouched after its evidence was gone). The
    rest (words next to a change, a quote not in the prose before either,
    a broken promise with no words) are asked again in this
    prose (`questions.ask_resolved`): resolved, it is dropped and named in
    `check_notes`; otherwise it stands (`STILL_THERE`), on the words the
    asking gave (verified), or with none: unverified (`CARRIED_UNPLACED`)
    for a contradiction, a broken promise as it was. A ruling on a dispute
    this run's extraction no longer raises doesn't stand (#734's review
    CR-4, as `_carry_standing`). Its rulings on disputes and endings carry
    too (`_carry_rulings`). What stands is this run's `open_findings`, for
    the next. A failed asking is a `GateError`."""
    from dataclasses import replace

    from storyforge.questions import QuestionError, ask_resolved, resolve_model
    earlier = list(run.open_findings or [])
    gone = {d.fact_id for d in _disputes(run, [])} - {d.fact_id for d in disputes}
    stale = [f for f in earlier if f.fact_id in gone and not f.established_scene]
    live = [f for f in earlier if not _among(f, stale)]
    diff = None if run.open_prose == prose else _diff(run.open_prose, prose)
    kept, again, took_out = [], [], []
    for f in live:
        if diff is None or (f.scene_quote and _in_untouched_text(f, diff, before=True)):
            kept.append(replace(f, checker=OPEN, carried=UNTOUCHED))
        elif _took_out(f, diff):
            took_out.append(f)
        else:
            again.append(f)
    still, resolved = [], []
    notes = []
    if again:
        try:
            got = ask_resolved(scene_id, prose, again, model=resolve_model(),
                               log_file=os.path.join(log_dir, f'gate-resolved-{scene_id}.json'))
        except QuestionError as e:
            raise GateError(str(e)) from e
        resolved = got.resolved
        for f, quote in got.standing:
            if quote:
                # words of this prose that verify: the old quote's problem is gone
                still.append(replace(f, scene_quote=quote, checker=OPEN, carried=STILL_THERE,
                                     problem=''))
            elif f.kind == 'broken-promise':
                still.append(replace(f, scene_quote='', checker=OPEN, carried=STILL_THERE))
            else:
                still.append(replace(f, checker=OPEN, carried=STILL_THERE,
                                     problem=f.problem or CARRIED_UNPLACED))
        notes = [f'asking whether they are still there: {n}' for n in got.notes]
    for f in kept + still:
        (result.check.unverified if f.problem else result.check.findings).append(f)
    result.open_findings, result.open_prose = kept + still, prose
    if not earlier:
        said = 're-check: no open reading; the open checker found nothing on the prose before'
    else:
        said = (f're-check: no open reading; of the open checker\'s {len(earlier)} finding(s) '
                f'on the prose before, {len(kept)} stand (their words untouched)')
        if again:
            said += (f', {len(again)} asked again in this prose: {len(still)} still there, '
                     f'{len(resolved)} resolved' + (f' ({_finding_names(resolved)})'
                                                    if resolved else ''))
        if took_out:
            said += (f', {len(took_out)} dropped: {TOOK_OUT} ({_finding_names(took_out)})')
        if stale:
            said += (f', {len(stale)} dropped: rulings on disputes this run\'s extraction no '
                     f'longer raises ({_finding_names(stale)})')
    result.check_notes += [said] + notes
    _carry_rulings(run, disputes, list(endings), diff, result)


def _same_check(a: Finding, b: Finding) -> bool:
    """#738: whether the open checker's finding `a` and the question
    layer's `b` are one problem: a contradiction with the same code on
    overlapping words about the same thing (the same fact id, or
    `checker.same_target` with a fact needed: the same source and
    established words), so two facts broken in one sentence stay two; or
    the same broken promise (`same_target`). When in doubt, two."""
    from storyforge.checker import same_target
    from storyforge.continuity import overlaps
    if a.kind != b.kind:
        return False
    if a.kind == 'broken-promise':
        return same_target(a, b, need_fact=True)
    if a.code != b.code or not overlaps(a.scene_quote, b.scene_quote):
        return False
    return bool(a.fact_id and a.fact_id == b.fact_id) or same_target(a, b, need_fact=True)


def _join_tandem(result: 'GateResult', got, disputes: list[Dispute],
                 endings: list[Dispute], open_read: bool) -> None:
    """#738: the question layer's answer `got` joined to a tandem run's
    check, which holds the open checker's reading (`open_read`) or the
    findings carried from it, and the shared layers' findings.

    - Findings: the union. A question finding the open checker also made
      (`_same_check`) is one, tagged `BOTH`; one on a shared layer's words
      and code is left out, as in `questions` mode; the rest are tagged
      `QUESTIONS`.
    - Brief reports: `kept` by fact, the rest without repeats.
    - Rulings (`_join_rulings`), with the facts the questions found
      contradicted read before any is left out as a repeat."""
    from storyforge.continuity import is_advisory, overlaps
    check = result.check
    q_found = {f.fact_id for f in list(got.findings) + list(got.unverified) if f.fact_id}
    opened = [f for f in check.findings + check.unverified if _from_open(f)]
    # an advisory continuity finding never stands in for a blocking one
    shared = [f for f in check.findings + check.unverified
              if not f.checker and not is_advisory(f)]
    for found, into in ((got.findings, check.findings), (got.unverified, check.unverified)):
        for f in found:
            same = next((g for g in opened if _same_check(g, f)), None)
            if same is not None:
                same.checker = BOTH
                continue
            if f.kind == 'contradiction' and any(
                    g.code == f.code and overlaps(g.scene_quote, f.scene_quote)
                    for g in shared):
                continue
            f.checker = QUESTIONS
            into.append(f)
    kept = {rid for rid, _ in check.kept}
    check.kept += [(rid, q) for rid, q in got.kept if rid not in kept]
    kept = {rid for rid, _ in check.kept}
    check.kept_unverified = [k for k in check.kept_unverified if k[0] not in kept]
    listed = {k[0] for k in check.kept_unverified}
    check.kept_unverified += [k for k in got.kept_unverified
                              if k[0] not in kept and k[0] not in listed]
    departed = {f.fact_id for f in check.plan_departures}
    check.plan_departures += [f for f in got.plan_departures if f.fact_id not in departed]
    check.unknown_brief_items = list(dict.fromkeys(check.unknown_brief_items
                                                   + list(got.unknown_brief_items)))
    check.stale_brief_items = list(dict.fromkeys(check.stale_brief_items
                                                 + list(got.stale_brief_items)))
    view = result.open_rulings or OpenRulings()
    _join_rulings(result, got, disputes, endings, view, q_found, open_read)


def _join_rulings(result: 'GateResult', got, disputes: list[Dispute],
                  endings: list[Dispute], view: OpenRulings, q_found: set[str],
                  open_read: bool) -> None:
    """#738: how a tandem run's two checkers rule on one dispute or ending.
    `view` is the open checker's rulings: its own reading's on a first run
    (`open_read`), on a re-check those carried from the first run where
    the fix left their words alone (`_carry_rulings`). `q_found` is every
    fact the questions found contradicted, those left out as repeats too.

    - A dispute either checker reported as a contradiction (a finding
      naming its fact, carried ones included) is a contradiction: a
      blocking finding from either stands.
    - Otherwise it is cleared when either cleared it, and else unruled,
      which blocks. One checker clearing what the other left unruled is
      cleared: the one that ruled read the scene and found no
      contradiction, and clearing keeps the plan's fact in the ledger.
    - An ending is recorded only when both say the scene shows it ending
      (#734: every reading of the open checker must, and two askings of the
      questions); either alone records nothing, and the end is held as a
      no is. On a re-check, one the open checker's view of didn't carry
      (asked now for the first time, or the fix changed its words) is the
      questions' alone, and a recorded one says so.

    Every disagreement, and every ruling one checker alone made on a
    re-check, is a `check_notes` line, so it is never silent."""
    check = result.check
    checked = [f for f in check.findings + check.unverified if f.checker]
    found = {f.fact_id for f in checked if f.fact_id} | q_found
    by_open = {f.fact_id for f in checked if _from_open(f) and f.fact_id}
    q_cleared = {d.fact_id for d in got.cleared}
    first = 'the open checker' if open_read else 'the open checker on the first run'
    cleared, unruled, notes = [], [], []
    for d in disputes:
        rid = d.fact_id
        seen = rid in view.disputes
        if rid in found:
            if rid in by_open and rid not in q_found and rid in q_cleared:
                notes.append(f'dispute on {rid}: {first} found it contradicted, the '
                             f'questions cleared it; the finding stands')
            elif rid in q_found and rid not in by_open and rid in view.cleared:
                notes.append(f'dispute on {rid}: the questions found it contradicted, {first} '
                             f'cleared it; the finding stands')
            continue
        if rid in view.cleared or rid in q_cleared:
            cleared.append(d)
            if rid not in q_cleared:
                notes.append(f'dispute on {rid}: {first} cleared it, the questions gave no '
                             f'ruling; cleared')
            elif seen and rid not in view.cleared:
                notes.append(f'dispute on {rid}: the questions cleared it, {first} gave no '
                             f'ruling; cleared')
        else:
            unruled.append(d)
    check.cleared, check.unruled = cleared, unruled
    q_ended = {d.fact_id for d in got.ended}
    ended = []
    for d in endings:
        rid = d.fact_id
        if rid not in view.endings:
            # a re-check: the open checker's view didn't carry
            if rid in q_ended:
                ended.append(d)
                notes.append(f'ending of {rid}: recorded on the questions\' answer alone; the '
                             f'open checker\'s view was not read again on this re-check')
            continue
        if (rid in view.ended) != (rid in q_ended):
            who, other = ((first, 'the questions') if rid in view.ended
                          else ('the questions', first))
            notes.append(f'ending of {rid}: {who} found the scene shows it ending, '
                         f'{other} did not; not recorded')
        elif rid in q_ended:
            ended.append(d)
    check.ended = ended
    result.check_notes += notes


def _ask_questions(project_dir: str, scene_id: str, prose: str, rows: list[dict[str, str]],
                   records: list, disputes: list[Dispute], log_dir: str,
                   result: 'GateResult', endings: list[Dispute] = (),
                   tandem: str = '') -> None:
    """The question layer in place of the open checker (#649): its
    contradictions join the check's (one on the same words with the same
    code as one the blocking check or the continuity checks already made is
    left out), and so do its broken promises (`unverified`: a `must:` beat
    in doubt), the promised facts it found established (`kept`, whose quotes
    the commit fills) and the rest of the brief's report; its rulings on
    `disputes` become the check's `cleared` and `unruled`; and its notes,
    with what it doesn't check (`QUESTION_LAYER_GAPS`), go to
    `result.question_notes`, logged and reported. A failure is a
    `GateError`.

    With `tandem` (#738: `READ`, beside the open checker's reading of this
    prose; `CARRIED`, beside the findings carried from it) it is joined to
    the open checker's instead (`_join_tandem`), and the notes say what a
    re-check doesn't read (`TANDEM_RECHECK_GAP`) in place of
    `QUESTION_LAYER_GAPS`, which a first run's open reading covers."""
    from storyforge.common import log
    from storyforge.continuity import is_advisory, overlaps
    from storyforge.questions import QuestionError, check_questions
    try:
        got = check_questions(project_dir, scene_id, prose=prose, rows=rows, records=records,
                              disputes=disputes, endings=endings,
                              log_file=os.path.join(log_dir, f'gate-questions-{scene_id}.json'))
    except QuestionError as e:
        raise GateError(str(e)) from e
    if tandem:
        _join_tandem(result, got, disputes, list(endings), open_read=tandem == READ)
        result.question_notes = list(got.notes) + ([] if tandem == READ
                                                   else [TANDEM_RECHECK_GAP])
        result.asked_fact_ids += [i for i in dict.fromkeys(got.asked_fact_ids)
                                  if i not in result.asked_fact_ids]
        log(f'  {scene_id}: questions: ' + '; '.join(got.notes))
        return
    # an advisory continuity finding never stands in for a blocking one
    have = [f for f in result.check.findings + result.check.unverified if not is_advisory(f)]
    for f in got.findings:
        if f.kind != 'contradiction' or not any(
                g.code == f.code and overlaps(g.scene_quote, f.scene_quote) for g in have):
            result.check.findings.append(f)
    check = result.check
    check.unverified += got.unverified
    check.kept += got.kept
    check.kept_unverified += got.kept_unverified
    check.plan_departures += got.plan_departures
    check.unknown_brief_items += got.unknown_brief_items
    check.stale_brief_items += got.stale_brief_items
    check.cleared += got.cleared
    check.unruled += got.unruled
    check.ended += got.ended
    result.question_notes = list(got.notes) + list(QUESTION_LAYER_GAPS)
    result.asked_fact_ids += [i for i in dict.fromkeys(got.asked_fact_ids)
                              if i not in result.asked_fact_ids]
    log(f'  {scene_id}: questions: ' + '; '.join(got.notes))


def gate_unchanged(project_dir: str, scene_id: str, *, command: str, log_dir: str,
                   introduced_by: str | None = None, extract_model: str | None = None,
                   check_model: str | None = None,
                   afford: Callable[[], bool] | None = None
                   ) -> tuple[GateResult, Reextraction | None]:
    """`gate_scene` of the scene file as it stands (a re-check, or
    `storyforge check`'s advisory or pending check), never editing it, with
    #598's one re-extraction when the extractor's slips alone stopped it
    (`_only_extractor_slips`, `_reextract`; logged in `log_dir/reextract`).
    #620 (Telemachy, 2026-11-07): a re-check's extractor joined two
    sentences across a dialogue tag into one quote, and the stop left 27
    later scenes pending; #598 gave only `gate_and_fix` the re-extraction.

    Returns the run kept and the `Reextraction` (None when there was none);
    the caller logs `.summary()` and reports it. A second misquote is kept
    and reported, never fuzzy-matched; a re-extraction that raises
    `GateError` keeps the first run (`REGATE_ERROR`). A re-extraction is a
    second gate run, paid like the first (`RECHECK_COST_PER_SCENE`):
    `afford()` False (the caller's cost threshold) skips it, and the
    `Reextraction` says so.

    A re-check (`command` 'recheck') is gated against a baseline of the
    scene's own gated prose only (`own_snapshot`, #631): a contradiction
    within the scene whose words were there when it last passed is
    inherited, as when revise gates it; one with any other scene, the
    ledger or a reference file still blocks (#480's review: that is what a
    re-check is for).

    Raises:
        GateError: from the first run.
        Exception: anything else, from either run (a bug, not the extractor).
    """
    before = own_snapshot(project_dir, scene_id) if command == 'recheck' else None
    result = gate_scene(project_dir, scene_id, command=command, log_dir=log_dir,
                        extract_model=extract_model, check_model=check_model,
                        introduced_by=introduced_by, before=before)
    if not _only_extractor_slips(result):
        return result, None
    if afford is not None and not afford():
        return result, Reextraction.of(result, error='not run: it would pass the cost '
                                                     'threshold')
    result, _, reextraction = _reextract(
        project_dir, scene_id, command, None, result, log_dir,
        extract_model=extract_model, check_model=check_model, before=before,
        fallback_dir=log_dir, introduced_by=introduced_by, catch_all=False)
    return result, reextraction


def own_snapshot(project_dir: str, scene_id: str) -> Snapshot | None:
    """#631: a `Snapshot` holding only `scene_id`'s gated prose (`gated_prose`,
    the prose its commitments were last read from), for a re-check: a
    finding set against the scene itself whose quotes were in that prose is
    inherited (`_classify`, `_unchanged_since`), and nothing else can be,
    since no other scene or reference file is in it. None (no baseline)
    when the gated prose can't be had; the log says so."""
    earlier, why = gated_prose(project_dir, scene_id)
    if earlier is None:
        from storyforge.common import log
        log(f'  {scene_id}: no baseline for findings within the scene ({why}); any it has '
            f'blocks')
        return None
    return Snapshot(scenes={scene_id: earlier})


def _one_line(text: str) -> str:
    return ' '.join(str(text).split())


#: `report_lines`' prefixes for what is reported either way, not what
#: stopped the commit
_NOT_BLOCKING = ('NOTE', 'COMMITTED', 'ALREADY IN THE SCENE', 'SOURCE BACKS THIS SCENE',
                 'ADVISORY')


def blocking_lines(lines: list[str]) -> list[str]:
    """The `report_lines` that name what stopped the commit."""
    return [line for line in lines if not line.startswith(_NOT_BLOCKING)]


#: #738: a tandem finding's tags in a report line, by `Finding.checker`
#: and `Finding.carried`
_CHECKER_TAG = {OPEN: 'open checker', QUESTIONS: 'questions',
                BOTH: 'open checker and questions'}
_CARRIED_TAG = {UNTOUCHED: 'from the first run; its words untouched by the fix',
                STILL_THERE: 'from the first run; still there after the fix'}


def _from_reading(f: Finding) -> str:
    """Which reading made `f`, past the first (its exchange is in
    gate-check-<scene>.rN.json, beside the first reading's log); under
    `tandem` (#738), which checker, and whether it was carried from the
    first run."""
    tags = [f'reading {f.reading}'] if f.reading > 1 else []
    tags += [t for t in (_CHECKER_TAG.get(f.checker), _CARRIED_TAG.get(f.carried)) if t]
    return ''.join(f' [{t}]' for t in tags)


def applied_lines(result: GateResult) -> list[str]:
    """The NOTE lines for the links extraction applied in its own way
    (`ENDS_MOVED`, `ID_PREFIX`, `UNOFFERED`, `ENDS_HERE`), as `report_lines`
    words them."""
    return [f'NOTE ({_REPORTED_LABEL[kind]}): '
            + '; '.join(_one_line(i) for i in result.problems.get(kind, []))
            for kind in (ENDS_MOVED, ID_PREFIX, UNOFFERED, ENDS_HERE) + _CLAIM_KINDS
            if result.problems.get(kind)] + claim_lines(result) + _held_slips_line(result)


def claim_lines(result: GateResult) -> list[str]:
    """#749's review: the NOTE lines for the claims in speech that no
    `REPORTED` kind carries: a kept fact a claim reads again, and a claim
    the source tells otherwise."""
    lines = []
    if result.unkept_as_claims:
        lines.append('NOTE (an earlier fact of unchanged prose is now read as a claim in '
                     'speech: no longer in force, counted as changed): '
                     + '; '.join(f'{rid} ("{_one_line(st)}")' for rid, st in
                                 result.unkept_as_claims))
    if result.claim_departs:
        lines.append(f'NOTE (a claim in speech tells otherwise than the source: kept as said, '
                     f'never blocking; listed in {SOURCE_NOTES_PATH}): '
                     + '; '.join(f'"{_one_line(st)}" ({_one_line(why)})'
                                 for st, why in result.claim_departs))
    return lines


def reread_lines(result: GateResult) -> list[str]:
    """#599: the proposed rows dropped as a reading again of a kept fact, and
    those recorded as new that read much like one, as NOTE lines."""
    lines = [f'NOTE (not recorded: a reading again of {rid}, from unchanged prose): '
             f'{_one_line(st)}' for st, rid in result.reread]
    lines += [f'NOTE (recorded as a new fact, but reads much like {rid}; check it is not a '
              f'copy): {_one_line(st)}' for st, rid in result.restates]
    return lines


#: What an `ADVISORY` line says (#642)
ADVISORY_LABEL = ('a broken promise; not blocking: the brief is a plan and the prose stands. '
                  'Amend the brief, or mark the beat `must:` to require it')
#: The `ADVISORY` label of an advisory continuity finding
#: (`continuity.is_advisory`: the typed knowledge check)
ADVISORY_KNOWLEDGE_LABEL = ('the typed knowledge check; not blocking: when a character learns '
                            'a fact is read from the briefs and the scenes\' typed state, which '
                            'often misplace it. Fix the prose, or the brief\'s knowledge_in '
                            'or knowledge_out, if it is wrong')


def _advisory_label(f: Finding) -> str:
    return ADVISORY_LABEL if f.kind == 'broken-promise' else ADVISORY_KNOWLEDGE_LABEL


def _advisory_message(f: Finding) -> str:
    """An advisory finding in words: a broken promise's promised item first
    (its scene quote is often empty); any other finding as reported
    (`Finding.message`)."""
    if f.kind != 'broken-promise':
        return f.message() + (f' (unverified: {f.problem})' if f.problem else '')
    what = f'the brief\'s {f.fact_id}' if f.fact_id else 'the brief'
    promised = f' "{f.established_quote}"' if f.established_quote else ''
    near = f'; nearest words: "{f.scene_quote}"' if f.scene_quote else ''
    return (f'{f.code} {what} promises{promised}{near} — {f.explanation}'
            + (f' (unverified: {f.problem})' if f.problem else ''))


#: The words an unruled dispute's `ADVISORY` line opens with
ADVISORY_UNRULED_LABEL = ('an unruled dispute; not blocking: extraction read the scene changing '
                          'a plan fact and the check gave no ruling, so the plan\'s fact stands. '
                          'Fix the plan, or the prose, if the scene does change it')
#: How an unruled dispute's row in `ADVISORY_PATH` is told from the others
#: (`is_unruled_row`): its `finding` opens with this
UNRULED_TAG = 'UNRULED: '


def _unruled_message(d: Dispute) -> str:
    """An unruled dispute in words, as its `ADVISORY` line and its row in
    `ADVISORY_PATH` give it."""
    return (f'{UNRULED_TAG}the scene may change the plan\'s {d.fact_id} '
            f'("{_one_line(d.statement)}"): "{_one_line(d.claim)}"; the check gave no ruling')


def advisory_report_lines(result: GateResult) -> list[str]:
    """The `ADVISORY` lines for `result.advisory` and `result.unruled`, as
    `report_lines` words them."""
    return ([f'ADVISORY ({_advisory_label(f)}; listed in {ADVISORY_PATH}){_from_reading(f)}: '
             f'{_one_line(_advisory_message(f))}' for f in result.advisory]
            + [f'ADVISORY ({ADVISORY_UNRULED_LABEL}; listed in {ADVISORY_PATH}): '
               f'{_unruled_message(d)}' for d in result.unruled])


def _promise_why(result: GateResult, f: Finding) -> str:
    """' (blocking: why)' for a broken promise that isn't advisory, else ''."""
    why = next((w for g, w in result.promise_why if g is f), '')
    return f' (blocking: {_one_line(why)})' if why else ''


def report_lines(result: GateResult) -> list[str]:
    """The gate's verdict on a scene as one-line strings (log lines, list
    items): everything that stopped the commit, then what is reported
    either way, then what was committed."""
    lines = []
    for h in result.halts:
        if h.planned:
            lines.append(f'HALT ({h.kind}; the plan calls for this change, so {h.fixed_id} is '
                         f'likely mis-typed fixed: not sent to the fix. If it can change, '
                         f'`storyforge check --unfix {h.fixed_id}`, then check the scene '
                         f'again; if it can\'t, fix the brief): {_one_line(h)}; '
                         f'{_one_line(h.planned)}')
        else:
            lines.append(f'HALT ({h.kind}): {_one_line(h)}')
    for item in result.unresolved:
        lines.append(f'EXTRACTION: {_one_line(item)}')
    lines += _held_slips_line(result)
    for f in result.findings:
        if _among(f, result.plan_conflicts):
            note = next((n for g, n in result.speaker_notes if g is f), '')
            lines.append(f'PLAN CONFLICT (the brief\'s own words contradict the book; fix the '
                         f'brief or {f.source}){_from_reading(f)}: {_one_line(f.message())}'
                         + (f' ({_one_line(note)})' if note else ''))
        else:
            lines.append(f'{f.kind.upper()}{_from_reading(f)}: {_one_line(f.message())}'
                         + _promise_why(result, f))
    for f in result.unverified:
        lines.append(f'UNVERIFIED ({f.problem}){_from_reading(f)}: '
                     f'{_one_line(f.message())}' + _promise_why(result, f))
    for f, why in result.source_backed:
        lines.append(f'SOURCE BACKS THIS SCENE (not blocking; {f.source} is listed for the '
                     f'author in {PENDING_PATH}): {_one_line(f.message())} — the source: '
                     f'{_one_line(why)}')
    if result.source_superseded:
        lines.append('NOTE (no longer binding: the source backs this scene against them): '
                     + ', '.join(result.source_superseded))
    for f, quote, why in result.source_has_it:
        lines.append(f'SOURCE HAS IT (still blocking: a slip inside the scene is smoothed; the '
                     f'passage is listed for the author in {SOURCE_NOTES_PATH}): '
                     f'{_one_line(f.message())} — the source: "{_one_line(quote)}" '
                     f'({_one_line(why)})')
    if result.source_departs:
        lines.append('NOTE (recorded, but the source contradicts it; the scene is listed for '
                     f'the author in {SOURCE_FIX_PATH}): '
                     + '; '.join(f'{_one_line(st)} ({_one_line(why)})'
                                 for st, why in result.source_departs))
    for note in result.source_notes:
        lines.append(f'NOTE (source): {_one_line(note)}')
    lines += advisory_report_lines(result)
    if result.bare_must:
        lines.append('NOTE (brief items that are only the must: marker; they mark nothing): '
                     + ', '.join(result.bare_must))
    if result.misplaced_must:
        lines.append('NOTE (brief items with a must: that marks nothing: the marker opens a '
                     'key_actions or key_dialogue item, before any label; these are advisory): '
                     + _one_line('; '.join(result.misplaced_must)))
    if result.short_must:
        lines.append(f'NOTE (must: lines under {_MIN_BRIEF_WORDS} words; too short to check '
                     f'word for word, left to the check): '
                     + _one_line('; '.join(result.short_must)))
    for f in result.inherited:
        lines.append(f'ALREADY IN THE SCENE (before this pass, or reported before; not '
                     f'blocking, the author\'s to fix; listed in {REPORTED_PATH} on commit): '
                     f'{_one_line(f.message())}')
    if result.held_back:
        lines.append('NOTE (not recorded: states a contradiction already in the scene): '
                     + '; '.join(_one_line(st) for st, _ in result.held_back))
    if result.disputed:
        lines.append(f'NOTE (recorded as disputed, not in force until its finding is '
                     f'accepted, `storyforge check --accept {result.scene_id}`, or a '
                     f're-check clears it: states what stopped the commit): '
                     + '; '.join(_one_line(st) for st, _ in result.disputed))
    if result.kept_stating:
        lines.append('NOTE (kept as it was, from unchanged prose, though it states '
                     + ('what stopped the commit' if result.provisional else
                        'a contradiction already in the scene') + '): '
                     + '; '.join(_one_line(st) for st, _ in result.kept_stating))
    if result.check:
        if not result.committed:
            for d in result.check.ended:
                lines.append(f'NOTE (the check found the scene shows a state the plan sets '
                             f'up in it ending; recorded when the scene commits): '
                             f'{d.fact_id} ("{_one_line(d.statement)}")')
        for d in result.check.cleared:
            lines.append(f'NOTE (plan fact kept, link not applied; the check found no '
                         f'contradiction): {d.fact_id} ("{_one_line(d.statement)}") vs '
                         f'"{_one_line(d.claim)}"')
    if result.ends_held:
        lines.append('NOTE (not recorded: the end of a state the plan sets up in this scene): '
                     + '; '.join(_one_line(h) for h in result.ends_held))
    for kind in REPORTED:
        if kind in ('disagrees', 'ends registry'):
            continue    # every one is a dispute: a finding, UNRULED or the note above
        items = result.problems.get(kind, [])
        cap = len(items) if kind in _CLAIM_KINDS else 20
        if items:
            lines.append(f'NOTE ({_REPORTED_LABEL.get(kind, kind)}): '
                         + '; '.join(_one_line(i) for i in items[:cap])
                         + (' ...' if len(items) > cap else ''))
    lines.extend(claim_lines(result))
    if result.check:
        for rid, quote, why in result.check.kept_unverified:
            lines.append(f'NOTE (kept, not filled): {rid}: {why}')
        if result.check.unknown_brief_items:
            lines.append('NOTE (brief items in words, no ledger fact; checked as words): '
                         + _one_line('; '.join(result.check.unknown_brief_items)))
        if result.check.plan_departures:
            lines.append('NOTE (the prose departs from planned facts; not an error, they '
                         'stay planned): ' + _one_line('; '.join(
                             f'{f.fact_id}: {f.explanation or f.kind}'
                             for f in result.check.plan_departures)))
        if result.check.stale_brief_items:
            lines.append('NOTE (brief items naming a fact that is not binding; not checked, '
                         'fix the brief): ' + _one_line('; '.join(result.check.stale_brief_items)))
    if result.dropped:
        lines.append(f'NOTE (not recorded, judged not to last beyond the scene): '
                     + '; '.join(f'{_one_line(st)} ({_one_line(why)})'
                                 for st, why in result.dropped[:20])
                     + (' ...' if len(result.dropped) > 20 else ''))
    if result.blocking_note:
        lines.append(f'NOTE (re-check): {result.blocking_note}')
    if result.stage_notes:
        lines.append('NOTE (stage sheet, not checked): '
                     + _one_line('; '.join(result.stage_notes)))
    if result.state_notes:
        lines.append('NOTE (continuity, not checked or advisory): '
                     + _one_line('; '.join(result.state_notes)))
    if result.question_notes:
        lines.append('NOTE (questions: what was asked, and what was not checked): '
                     + _one_line('; '.join(result.question_notes)))
    if result.check_notes:
        lines.append('NOTE (tandem: which checkers read it, and where they disagree): '
                     + _one_line('; '.join(result.check_notes)))
    if result.steady:
        lines.append(f'NOTE (kept as they were, read from paragraphs the prose has unchanged): '
                     f'{len(result.steady)} fact(s)')
    for note in result.prose_notes:
        lines.append(f'NOTE (re-check): {_one_line(note)}')
    lines += reread_lines(result)
    if result.committed:
        lines.append(f'COMMITTED{" (provisionally: listed " + PENDING_PATH + ")" if result.provisional else ""}: {len(result.proposed)} fact(s)'
                     + (f'; quotes filled: {", ".join(result.quotes_filled)}'
                        if result.quotes_filled else ''))
    return lines


# ============================================================================
# Scenes waiting on the gate: working/gate-pending.csv
# ============================================================================

#: Scenes whose prose is on disk but didn't pass the gate, so their facts
#: aren't in the ledger. `write` won't draft a later scene that depends on
#: one (it would be drafted from an incomplete ledger; `cmd_write.GateBlockers`,
#: #641), and drafts the others; a pass, through `write` or
#: `storyforge check`, takes it off.
PENDING_PATH = 'working/gate-pending.csv'
_PENDING_COLUMNS = ['scene_id', 'command', 'reason']


def _pending_file(project_dir: str) -> str:
    return os.path.join(project_dir, PENDING_PATH)


def pending(project_dir: str) -> dict[str, dict[str, str]]:
    """Scene id → {scene_id, command, reason} for each scene waiting on the gate."""
    path = _pending_file(project_dir)
    if not os.path.isfile(path):
        return {}
    with open(path, encoding='utf-8') as f:
        lines = [line.rstrip('\n') for line in f if line.strip()]
    if not lines or lines[0].split('|') != _PENDING_COLUMNS:
        raise GateError(f'{PENDING_PATH}: the header must be {"|".join(_PENDING_COLUMNS)}')
    out = {}
    for line in lines[1:]:
        cells = line.split('|')
        if len(cells) != len(_PENDING_COLUMNS):
            raise GateError(f'{PENDING_PATH}: a row with {len(cells)} cells: {line[:80]!r}')
        out[cells[0]] = dict(zip(_PENDING_COLUMNS, cells))
    return out


def _write_pending(project_dir: str, rows: dict[str, dict[str, str]]) -> None:
    path = _pending_file(project_dir)
    if not rows:
        if os.path.isfile(path):
            os.remove(path)
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='') as f:
        f.write('|'.join(_PENDING_COLUMNS) + '\n')
        for row in rows.values():
            f.write('|'.join(row[c] for c in _PENDING_COLUMNS) + '\n')


def mark_pending(project_dir: str, scene_id: str, command: str, reason: str) -> None:
    """List `scene_id`. A `REVISE_REJECTED` row keeps that command and its
    rejected fact ids whatever replaces it (a failed check of the revision):
    the ids are what lists the dependents once the scene passes."""
    from storyforge.common import csv_safe
    rows = pending(project_dir)
    old = rows.get(scene_id)
    ids = rejected_ids(old) + (rejected_ids({'command': command, 'reason': reason})
                               if command == REVISE_REJECTED else [])
    if old and old.get('command') == PROVISIONAL and command == 'advisor':
        # #556's review: a failed check of a provisional scene leaves its
        # provisional facts in the ledger; it is still provisional
        command = PROVISIONAL
    if ids:
        command = REVISE_REJECTED
        reason = re.sub(r'\s*\[rejected: [^\]]*\]', '', reason) \
            + f' [rejected: {";".join(dict.fromkeys(ids))}]'
    rows[scene_id] = {'scene_id': scene_id, 'command': command, 'reason': csv_safe(reason)}
    _write_pending(project_dir, rows)


def rejected_ids(row: dict[str, str] | None) -> list[str]:
    """The rejected fact ids a `REVISE_REJECTED` pending row carries."""
    if not row or row.get('command') != REVISE_REJECTED:
        return []
    ids = [i for group in re.findall(r'\[rejected: ([^\]]*)\]', row.get('reason', ''))
           for i in group.split(';') if i]
    return list(dict.fromkeys(ids))


def clear_pending(project_dir: str, scene_id: str) -> None:
    rows = pending(project_dir)
    if rows.pop(scene_id, None) is not None:
        _write_pending(project_dir, rows)


# ============================================================================
# Errors already in the book: working/gate-reported.csv
# ============================================================================

#: The contradictions a gate run found already in the book (`inherited`)
#: and let through, one row each, so the author has them after the run's
#: log scrolls by. Not a block: `write` and `revise` go on past them. A
#: scene's rows are replaced each time it commits; a gate run of the scene
#: that finds one of them again (same source and quote, any command) counts
#: it inherited. Rows whose `command` is `ACCEPTED` are the author's
#: (`storyforge check --accept`): they survive the replacement, so a check
#: that happens not to raise one doesn't forget it (the checker's findings
#: vary run to run), and go only when their quote leaves the scene's prose.
REPORTED_PATH = 'working/gate-reported.csv'
#: `paragraphs` (#631): for a blocking finding (BLK) against the scene
#: itself, the keys (`_paragraph_key`) of the paragraphs its two quotes lie
#: in, `;`-joined, so an accepted one covers a new reading of the same
#: unchanged paragraphs; blank otherwise
_REPORTED_COLUMNS = ['scene_id', 'command', 'source', 'quote', 'finding', 'paragraphs']
#: the header before #631, still read (its rows have no paragraphs)
_OLD_REPORTED_COLUMNS = _REPORTED_COLUMNS[:-1]
#: The `command` of a row the author accepted (`storyforge check --accept`)
ACCEPTED = 'accepted'
#: The verified contradictions that stopped each scene's last gate run, the
#: rows `storyforge check --accept` moves to `REPORTED_PATH` (Ben,
#: 2026-11-02: a stop on an error in the book is the author's to fix or
#: accept). Same columns; replaced by each gate run of the scene that gets
#: to the check, put back to the kept run's when `gate_and_fix` discards a
#: fix, and cleared when it commits.
BLOCKED_PATH = 'working/gate-blocked.csv'


def _read_rows(project_dir: str, rel: str) -> dict[str, list[dict[str, str]]]:
    path = os.path.join(project_dir, rel)
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding='utf-8') as f:
            lines = [line.rstrip('\n') for line in f if line.strip()]
    except (OSError, UnicodeDecodeError) as e:
        raise GateError(f'{rel}: {e}') from e
    header = lines[0].split('|') if lines else []
    if header not in (_REPORTED_COLUMNS, _OLD_REPORTED_COLUMNS):
        raise GateError(f'{rel}: the header must be {"|".join(_REPORTED_COLUMNS)}')
    out: dict[str, list[dict[str, str]]] = {}
    for line in lines[1:]:
        cells = line.split('|')
        if len(cells) != len(header):
            raise GateError(f'{rel}: a row with {len(cells)} cells: {line[:80]!r}')
        row = dict(zip(header, cells))
        row.setdefault('paragraphs', '')
        out.setdefault(row['scene_id'], []).append(row)
    return out


def _write_rows(project_dir: str, rel: str, rows: dict[str, list[dict[str, str]]]) -> None:
    """Write `rows` to `rel`; the file goes when there are none."""
    path = os.path.join(project_dir, rel)
    if not any(rows.values()):
        if os.path.isfile(path):
            os.remove(path)
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='') as f:
        f.write('|'.join(_REPORTED_COLUMNS) + '\n')
        for sid in sorted(rows):
            for row in rows[sid]:
                f.write('|'.join(row[c] for c in _REPORTED_COLUMNS) + '\n')


def _paragraph_key(words: tuple[str, ...] | list[str]) -> str:
    """A paragraph's key: a hash of its words (case, punctuation and spacing
    aside, as `steady_paragraphs` compares them), so a key still in the
    prose means the paragraph is there unchanged."""
    import hashlib
    return hashlib.sha1(' '.join(words).encode('utf-8')).hexdigest()[:12]


def _quote_paragraphs(quote: str, prose: str) -> set[str] | None:
    """The keys of the paragraphs of `prose` that `quote` lies in (every
    place it is found; a quote across paragraphs names each), or None when
    it isn't found."""
    paras = _paragraphs(prose)
    words: list[str] = []
    owner: list[int] = []
    for i, p in enumerate(paras):
        words += p
        owner += [i] * len(p)
    spans = _quote_spans(quote, words) if quote.strip() else []
    if not spans:
        return None
    return {_paragraph_key(paras[owner[k]]) for sp in spans for k in range(sp.start, sp.end)}


def _blocking_paragraphs(scene_id: str, f: Finding, prose: str) -> str:
    """`_REPORTED_COLUMNS`' `paragraphs` for `f`: the paragraphs both its
    quotes lie in, for a blocking finding against the scene itself ('' for
    any other, or when a quote can't be placed in `prose`)."""
    if f.code != BLOCKING_CODE or (f.established_scene or '') != scene_id or not prose:
        return ''
    keys = set()
    for quote in (f.scene_quote, f.established_quote):
        found = _quote_paragraphs(quote or '', prose)
        if found is None:
            return ''
        keys |= found
    return ';'.join(sorted(keys))


def _finding_rows(scene_id: str, command: str, findings: list[Finding],
                  prose: str = '') -> list[dict[str, str]]:
    from storyforge.common import csv_safe
    return [{'scene_id': scene_id, 'command': command,
             'source': csv_safe(f.established_scene or ''),
             'quote': csv_safe(_one_line(f.scene_quote)),
             'finding': csv_safe(_one_line(f.message())),
             'paragraphs': _blocking_paragraphs(scene_id, f, prose)} for f in findings]


def _accepted_blocking_covers(row: dict[str, str], f: Finding, scene_id: str,
                              prose: str) -> bool:
    """#631: whether the author's accepted blocking finding `row` covers `f`,
    a new reading of the scene's blocking: both are BLK against the scene
    itself, and each of `f`'s quotes lies only in paragraphs `row` was
    accepted on, which `prose` still has word for word (a paragraph's key
    is a hash of its words). The blocking read words the same slip
    otherwise from one reading to the next (iliad-teen, 2026-11-08: three
    rounds of accepts and new readings of the same unchanged paragraphs)."""
    if (row.get('command') != ACCEPTED or not row.get('paragraphs')
            or row.get('source') != scene_id or not row.get('finding', '').startswith(
                f'{BLOCKING_CODE} ')
            or f.code != BLOCKING_CODE or (f.established_scene or '') != scene_id):
        return False
    allowed = set(row['paragraphs'].split(';'))
    for quote in (f.scene_quote, f.established_quote):
        found = _quote_paragraphs(quote or '', prose)
        if found is None or not found <= allowed:
            return False
    return True


def _same(a: dict[str, str], b: dict[str, str]) -> bool:
    """Whether two rows are the same finding, as `_classify` matches one:
    the same source and quote."""
    return a['source'] == b['source'] and _words(a['quote']) == _words(b['quote'])


def reported(project_dir: str) -> dict[str, list[dict[str, str]]]:
    """Scene id → its rows in `REPORTED_PATH`.

    Raises:
        GateError: the file is malformed or unreadable.
    """
    return _read_rows(project_dir, REPORTED_PATH)


def blocked(project_dir: str) -> dict[str, list[dict[str, str]]]:
    """Scene id → its rows in `BLOCKED_PATH` (`GateError` as `reported`)."""
    return _read_rows(project_dir, BLOCKED_PATH)


def record_reported(project_dir: str, scene_id: str, command: str,
                    findings: list[Finding], prose: str | None = None,
                    keep_blocking: bool = False) -> None:
    """Replace `scene_id`'s rows in `REPORTED_PATH` with `findings`, keeping
    the author's `ACCEPTED` rows (a finding matching one isn't added again)
    except, with `prose`, those whose quote is no longer in it. With
    `keep_blocking` (#631: the run skipped the blocking read, so it can't
    report its findings again) the scene's reported blocking findings are
    kept too, on the same terms. The file goes when it has no rows."""
    rows = reported(project_dir)
    accepted = [r for r in rows.pop(scene_id, [])
                if (r['command'] == ACCEPTED
                    or (keep_blocking and r['finding'].startswith(f'{BLOCKING_CODE} ')))
                and (prose is None or _quoted_in(r['quote'], prose))]
    new = [r for r in _finding_rows(scene_id, command, findings)
           if not any(_same(r, a) for a in accepted)]
    if accepted or new:
        rows[scene_id] = accepted + new
    _write_rows(project_dir, REPORTED_PATH, rows)


def record_blocked(project_dir: str, scene_id: str, command: str,
                   findings: list[Finding], prose: str = '') -> None:
    """Replace `scene_id`'s rows in `BLOCKED_PATH` with `findings` (none:
    its rows go). With `prose` (the prose the run read), a blocking finding
    against the scene itself records the paragraphs its quotes lie in, so
    an accept of it covers the same paragraphs (#631)."""
    rows = blocked(project_dir)
    rows.pop(scene_id, None)
    if findings:
        rows[scene_id] = _finding_rows(scene_id, command, findings, prose)
    _write_rows(project_dir, BLOCKED_PATH, rows)


# ============================================================================
# Broken promises that don't block: working/gate-advisory.csv (#642)
# ============================================================================

#: The advisory findings of each scene's last gate run (#642): broken
#: promises and advisory continuity findings (`continuity.is_advisory`).
#: `REPORTED_PATH`'s columns, `source` the brief field (or registry id; a
#: continuity finding's fact id), `quote` the promised item (the
#: established words), `finding` the report's words, and `paragraphs` what the run read
#: (`_advisory_stamp`: `prose=<key>;brief=<key>`), so a row the scene or its
#: brief has since moved past can be told (`read_advisory`). Replaced by
#: each gate run of the scene that gets to the check, pass or not, and put
#: back to the kept run's when `gate_and_fix` discards a fix. `status`
#: lists them, and so do `check`, `write` and `revise` at the end of a run
#: (`advisory_summary`).
ADVISORY_PATH = 'working/gate-advisory.csv'


def advisories(project_dir: str) -> dict[str, list[dict[str, str]]]:
    """Scene id → its rows in `ADVISORY_PATH` (`GateError` as `reported`)."""
    return _read_rows(project_dir, ADVISORY_PATH)


def _brief_key(project_dir: str, scene_id: str) -> str:
    """A key of the scene's brief promises (`_paragraph_key` of their words):
    the same key, the same promises."""
    from storyforge.checker import PROMISE_FIELDS, REGISTRY_PROMISE_FIELDS
    scene = _brief_row(project_dir, scene_id)
    cells = [f'{c}={scene.get(c) or ""}' for c in (*PROMISE_FIELDS, *REGISTRY_PROMISE_FIELDS)]
    return _paragraph_key(_words(' | '.join(cells)).split())


def _prose_key(prose: str) -> str:
    return _paragraph_key(_words(prose).split())


def _advisory_stamp(project_dir: str, scene_id: str, prose: str) -> str:
    """`ADVISORY_PATH`'s `paragraphs` for a run that read `prose`."""
    return f'prose={_prose_key(prose)};brief={_brief_key(project_dir, scene_id)}'


def record_advisory(project_dir: str, scene_id: str, command: str,
                    findings: list[Finding], prose: str = '',
                    unruled: list[Dispute] = ()) -> None:
    """Replace `scene_id`'s rows in `ADVISORY_PATH` with `findings` and
    `unruled` (the disputes the check gave no ruling on: `source` the plan
    fact, `quote` its statement, `finding` `UNRULED_TAG` and the claim;
    `is_unruled_row`). None of either: its rows go; the file goes when it
    has no rows. `prose`: what the run read, stamped on each row
    (`_advisory_stamp`)."""
    from storyforge.common import csv_safe
    rows = advisories(project_dir)
    rows.pop(scene_id, None)
    if findings or unruled:
        stamp = _advisory_stamp(project_dir, scene_id, prose) if prose else ''
        rows[scene_id] = ([{'scene_id': scene_id, 'command': command,
                            'source': csv_safe(f.fact_id or ''),
                            'quote': csv_safe(_one_line(f.established_quote)),
                            'finding': csv_safe(_one_line(_advisory_message(f))),
                            'paragraphs': stamp} for f in findings]
                          + [{'scene_id': scene_id, 'command': command,
                              'source': csv_safe(d.fact_id),
                              'quote': csv_safe(_one_line(d.statement)),
                              'finding': csv_safe(_unruled_message(d)),
                              'paragraphs': stamp} for d in unruled])
    _write_rows(project_dir, ADVISORY_PATH, rows)


def _note_advisory(project_dir: str, scene_id: str, command: str,
                   result: 'GateResult', prose: str = '') -> str:
    """Record `result.advisory` and `result.unruled` (`record_advisory`),
    stamped with `prose` (the run's, `result._ctx.prose`, when not given). A file that can't be
    read or written is said, the gate's verdict unchanged (its report lines
    still name each one), and returned ('' when written)."""
    if not prose and getattr(result, '_ctx', None) is not None:
        prose = result._ctx.prose
    try:
        record_advisory(project_dir, scene_id, command, result.advisory, prose=prose,
                        unruled=result.unruled)
    except (GateError, OSError) as e:
        from storyforge.common import log
        why = f'{ADVISORY_PATH} could not be updated: {e}'
        log(f'WARNING: {scene_id}: {why}. Its advisory findings are only in this log.')
        return why
    return ''


#: `read_advisory`'s `stale` for a row whose scene or brief changed since
#: its gate run
STALE_PROSE = 'the scene has changed since this was found; re-check it'
STALE_BRIEF = 'the brief has changed since this was found; re-check the scene'


class Advisory(NamedTuple):
    """`read_advisory`'s answer (#642's review TD-2, TD-3, CR-4, SF-5)."""
    #: one per advisory broken promise, in reading order where known:
    #: `{scene_id, command, source, quote, finding, stale}`, `stale` '' or
    #: why the row may no longer hold (`STALE_PROSE`, `STALE_BRIEF`)
    rows: list[dict[str, str]]
    #: what couldn't be read (the file, the reading order), one line each:
    #: never a promise, and never silent
    problems: list[str]


def _stale(project_dir: str, row: dict[str, str]) -> str:
    stamp = dict(part.split('=', 1) for part in (row.get('paragraphs') or '').split(';')
                 if '=' in part)
    if not stamp:
        return ''
    from storyforge.illustrations import read_scene_raw
    try:   # the bytes the gate reads (`gate_scene`), markers and all; None: no file
        prose = read_scene_raw(project_dir, row['scene_id'])
    except (OSError, UnicodeDecodeError):
        prose = None
    if prose is None or ('prose' in stamp and _prose_key(prose) != stamp['prose']):
        return STALE_PROSE
    if 'brief' in stamp and _brief_key(project_dir, row['scene_id']) != stamp['brief']:
        return STALE_BRIEF
    return ''


def read_advisory(project_dir: str, scene_ids=None) -> Advisory:
    """The advisory broken promises in `ADVISORY_PATH` (of `scene_ids` only,
    when given). A file that can't be read gives no rows and one problem; a
    reading order that can't be read leaves the rows unordered and says so."""
    try:
        by_scene = advisories(project_dir)
    except GateError as e:
        return Advisory([], [f'{ADVISORY_PATH} could not be read: {e}'])
    problems = []
    try:
        order = ledger.scene_order(project_dir)
    except (ledger.LedgerError, ValueError, OSError) as e:
        order = {}
        problems.append(f'{ADVISORY_PATH}: listed unordered, the reading order could not be '
                        f'read: {e}')
    wanted = None if scene_ids is None else set(scene_ids)
    rows = []
    for sid in sorted(by_scene, key=lambda s: (order.get(s, 10**9), s)):
        if wanted is not None and sid not in wanted:
            continue
        for row in by_scene[sid]:
            rows.append({'scene_id': sid, 'command': row['command'],
                         'source': row['source'], 'quote': row['quote'],
                         'finding': row['finding'], 'stale': _stale(project_dir, row)})
    return Advisory(rows, problems)


def advisory_line(row: dict[str, str]) -> str:
    """One `read_advisory` row in words: `scene: finding`, and why it may be
    stale."""
    return (f'{row["scene_id"]}: {row["finding"]}'
            + (f' ({row["stale"]})' if row.get('stale') else ''))


def advisory_lines(project_dir: str, scene_ids=None) -> list[str]:
    """`read_advisory`'s rows, one line each (`advisory_line`); its
    problems are not among them (`advisory_summary` says those)."""
    return [advisory_line(r) for r in read_advisory(project_dir, scene_ids).rows]


def is_knowledge_row(row: dict[str, str]) -> bool:
    """Whether an `ADVISORY_PATH` row is the typed knowledge check's (its
    finding as `_advisory_message` words it), not a broken promise."""
    return '(typed state, knowledge)' in (row.get('finding') or '')


def is_unruled_row(row: dict[str, str]) -> bool:
    """Whether an `ADVISORY_PATH` row is an unruled dispute's
    (`_unruled_message`), not a broken promise or a knowledge finding."""
    return (row.get('finding') or '').startswith(UNRULED_TAG)


def advisory_summary(project_dir: str, scene_ids=None) -> list[str]:
    """The advisory findings of `scene_ids` (every scene when None) in
    `ADVISORY_PATH`, broken promises, then the typed knowledge check's
    (`is_knowledge_row`), then the disputes the check gave no ruling on
    (`is_unruled_row`), each kind as a WARNING line and one line each,
    after a WARNING for each thing that couldn't be read; none of either:
    []. They don't stop a scene; `check`, `write` and `revise` list them at
    the end of a run so the author can amend a brief, mark a beat `must:`,
    fix a knowledge slip that is real, or a plan fact the scene does change."""
    found = read_advisory(project_dir, scene_ids)
    lines = [f'WARNING: {p}' for p in found.problems]
    unruled = [r for r in found.rows if is_unruled_row(r)]
    promises = [r for r in found.rows if not is_knowledge_row(r) and not is_unruled_row(r)]
    knowing = [r for r in found.rows if is_knowledge_row(r)]
    if promises:
        lines += ([f'WARNING: {len(promises)} broken promise(s) the gate reported but did '
                   f'not stop on (advisory, {ADVISORY_PATH}, as of each scene\'s last gate '
                   f'run): the prose stands. Amend the brief, or mark the beat `must:` in '
                   f'key_actions or key_dialogue to require it:']
                  + [f'  {advisory_line(r)}' for r in promises])
    if knowing:
        lines += ([f'WARNING: {len(knowing)} use(s) of a fact before the scene that shows it '
                   f'learned, by the typed knowledge check, which the gate reported but did '
                   f'not stop on (advisory, {ADVISORY_PATH}, as of each scene\'s last gate '
                   f'run): often the brief misplaces the learning. Fix the prose, or the '
                   f'brief\'s knowledge_in or knowledge_out, where one is wrong:']
                  + [f'  {advisory_line(r)}' for r in knowing])
    if unruled:
        lines += ([f'WARNING: {len(unruled)} plan fact(s) the scene may change that the check '
                   f'gave no ruling on, which the gate reported but did not stop on (advisory, '
                   f'{ADVISORY_PATH}, as of each scene\'s last gate run): the plan\'s fact '
                   f'stands. Fix the plan, or the prose, where the scene does change it:']
                  + [f'  {advisory_line(r)}' for r in unruled])
    return lines


def _note_blocked(project_dir: str, scene_id: str, command: str, result: 'GateResult') -> str:
    """Record the verified contradictions that stopped `result`, for
    `storyforge check --accept`. A file that can't be read or written
    (malformed, or an OS error: SF-1, #504's review) is said, the gate's
    verdict unchanged, and returned ('' when written): its rows may then
    describe another run's prose, which `accept_blocked` refuses."""
    try:
        ctx = getattr(result, '_ctx', None)
        record_blocked(project_dir, scene_id, command,
                       [f for f in result.findings if f.kind == 'contradiction'],
                       prose=ctx.prose if ctx is not None else '')
    except (GateError, OSError) as e:
        from storyforge.common import log
        why = f'{BLOCKED_PATH} could not be updated: {e}'
        log(f'WARNING: {scene_id} did not pass, and {why}. Its contradictions can\'t be '
            f'accepted until a check records them.')
        return why
    return ''


def accept_blocked(project_dir: str, scene_id: str, promoted: list[str] | None = None,
                   listed: list[str] | None = None,
                   notes: list[str] | None = None) -> list[dict[str, str]]:
    """The author accepts the verified contradictions that stopped
    `scene_id`'s last gate run (Ben, 2026-11-02): its `BLOCKED_PATH` rows
    move to `REPORTED_PATH` as `ACCEPTED`, so later gate runs of the scene
    report them, not stop on them, and a `RECHECK_FAILED` listing goes back
    to `RECHECK` (the author has acted). The scene's commitments a
    provisional commit recorded as disputed (#735, `is_held`) come into
    force once every finding they state is accepted, here or before
    (`binding`, `reviewed` blank, so the audit digest lists them), with the
    earlier states they end (`_bring_into_force`); their ids go to
    `promoted`, the later scenes listed for a re-check because of them
    (#735's review SF-1: they were gated while the facts were held) to
    `listed`, and what couldn't be applied to `notes`. Returns the rows
    accepted (none: nothing is recorded for the scene, nothing changed).

    Raises:
        GateError: a file is malformed or can't be written. The ledger is
            written last (#735's review SF-4): when it alone fails, the
            findings are accepted and the message says to run
            `storyforge check --pending`, whose re-gate commits the facts."""
    stopped = blocked(project_dir)
    rows = stopped.pop(scene_id, [])
    if not rows:
        return []
    # SF-1 (#504's review): a run whose rows couldn't be replaced leaves
    # another prose's findings; accept only what the scene on disk says
    try:
        with open(os.path.join(project_dir, 'scenes', f'{scene_id}.md'),
                  encoding='utf-8') as f:
            prose = f.read()
    except (OSError, UnicodeDecodeError) as e:
        raise GateError(f'{scene_id}: can\'t read the scene to match its recorded '
                        f'contradictions: {e}') from e
    gone = [r['quote'] for r in rows if not _found_in(r['quote'], prose)]
    if gone:
        raise GateError(f'{scene_id}: {len(gone)} recorded contradiction(s) quote words not '
                        f'in the scene ("{gone[0][:80]}"): {BLOCKED_PATH} describes other '
                        f'prose; nothing accepted. Run `storyforge check {scene_id}` to '
                        f'record what this prose has.')
    kept = reported(project_dir)
    mine = kept.setdefault(scene_id, [])
    for r in rows:
        mine[:] = [m for m in mine if not _same(m, r)]
        mine.append({**r, 'command': ACCEPTED})
    _write_rows(project_dir, REPORTED_PATH, kept)
    _write_rows(project_dir, BLOCKED_PATH, stopped)
    row = pending(project_dir).get(scene_id)
    if row and row['command'] == RECHECK_FAILED:
        mark_pending(project_dir, scene_id, RECHECK,
                     f're-check: the author accepted {len(rows)} finding(s)')
    _bring_into_force(project_dir, scene_id, [m for m in mine if m['command'] == ACCEPTED],
                      promoted, listed, notes)
    return rows


def _bring_into_force(project_dir: str, scene_id: str, accepted: list[dict[str, str]],
                      promoted: list[str] | None, listed: list[str] | None = None,
                      notes: list[str] | None = None) -> None:
    """`accept_blocked`'s ledger side (#735): `scene_id`'s disputed
    commitments every one of whose findings is in `accepted` (the scene's
    accepted rows; #735's review CR-4) become binding, and the earlier
    states their stamp says they end (`held_parts`) end here, as
    `_apply_ends` would have: one already ended at or before the scene is
    left, said in `notes`. The later scenes depending on what came into
    force are listed `RECHECK` (#735's review SF-1). Writes only when a fact
    comes into force; ids to `promoted`, scenes to `listed`."""
    keys = {finding_row_key(r) for r in accepted}
    try:
        rows = ledger.load(project_dir)
        order = ledger.scene_order(project_dir)
        by_id = {r['id']: r for r in rows}
        ids, changed, said = [], [], []
        for r in rows:
            if not (is_held(r) and (r.get('scene_id') or '').strip() == scene_id):
                continue
            mine, ends = held_parts(r['reviewed'])
            if not mine or not set(mine) <= keys:
                continue
            r['status'], r['reviewed'] = 'binding', ''
            ids.append(r['id'])
            for sid in ends:
                state = by_id.get(sid)
                end = (state.get('resolves') or '').strip() if state else ''
                if state is None or state.get('status') != 'binding':
                    said.append(f'{r["id"]} ends {sid}, which is not a binding fact in the '
                                f'ledger now: not applied')
                elif end and end in order and scene_id in order and order[end] <= order[scene_id]:
                    said.append(f'{r["id"]} ends {sid}, which {end} already ends: not applied')
                else:
                    state['resolves'] = scene_id
                    changed.append(sid)
                    if end and end != scene_id:   # moved here from a later scene
                        changed.append(f'{sid}@{end}')
        if ids:
            ledger.save(project_dir, rows, command='accept')
    except (ledger.LedgerError, ValueError, OSError) as e:
        raise GateError(f'{scene_id}: the findings are accepted, but the facts disputed for '
                        f'them could not be brought into force ({e}); run `storyforge check '
                        f'--pending`, whose re-gate of the scene commits them') from e
    if promoted is not None:
        promoted.extend(ids)
    if notes is not None:
        notes.extend(said)
    if ids:
        scenes = _list_for_force(project_dir, scene_id, rows, ids + [c for c in changed
                                                                      if '@' not in c],
                                 order, moved=[c.split('@')[1] for c in changed if '@' in c])
        if listed is not None:
            listed.extend(scenes)


def _list_for_force(project_dir: str, scene_id: str, rows: list[dict[str, str]],
                    ids: list[str], order: dict[str, int], moved: list[str] = ()) -> list[str]:
    """#735's review SF-1: list `RECHECK` the later scenes, with prose, whose
    facts depend on `ids` (facts of `scene_id` that came into force, and the
    states they end), plus `moved` (scenes whose end of a state moved here):
    they were gated while the facts were held. A scene already waiting
    stays as it is. Returns the scenes listed."""
    names, _ = ledger.subject_names(project_dir)
    found = ledger.dependents(rows, ids, order, names=names, narrow=True)
    later = sorted({s for s in list(found.scenes) + list(moved)
                    if s in order and order[s] > order.get(scene_id, -1)}, key=order.get)
    gone = _gone_scenes(project_dir)
    scenes = [s for s in later if s not in gone and _has_prose(project_dir, s)]
    waiting = pending(project_dir)
    for s in scenes:
        if s not in waiting:
            why = found.why.get(s) or 'an end moved here from it'
            mark_pending(project_dir, s, RECHECK,
                         f're-check: {len(ids)} fact(s) of {scene_id} recorded as disputed came '
                         f'into force (`check --accept`) ({why})')
    return scenes


def held_facts(project_dir: str, scene_ids: list[str] | None = None) -> dict[str, list[str]]:
    """Scene id → the statements of its commitments recorded as disputed
    (#735, `is_held`), for the scenes named (every scene: None).

    Raises:
        GateError: the ledger can't be read."""
    try:
        rows = ledger.load(project_dir)
    except ledger.LedgerError as e:
        raise GateError(str(e)) from e
    out: dict[str, list[str]] = {}
    for r in rows:
        sid = (r.get('scene_id') or '').strip()
        if is_held(r) and (scene_ids is None or sid in scene_ids):
            out.setdefault(sid, []).append(r.get('statement', ''))
    return out


# ============================================================================
# The re-check (Phase 4, docs/plans/2026-10-31-phase4-safe-revision-design.md §3)
# ============================================================================

#: What one re-gated scene is forecast to cost: an extraction and a
#: persistence call (Sonnet) and `GATE_READINGS` checks (Opus, the story so
#: far cached). E4's one-reading gate ran about $0.35-0.45 a scene on
#: shared-dark, and a second reading about $0.35 more against a cold cache
#: (E8, 2026-11-01); rounded up. The blocking read (#626) is
#: `blocking.BLOCKING_READINGS` more calls on the scene alone (three since
#: #774), at `blocking.COST_PER_READING` each (about $0.035-0.04, rounded
#: up). The continuity checks' typed state extraction (#648,
#: `GATE_CONTINUITY`) is one more small-model call
#: on the scene (none when its saved file is current), about $0.01 a scene
#: at the extraction tier: covered by the rounding.
_BLOCKING_COST = BLOCKING_READINGS * BLOCKING_COST_PER_READING if GATE_BLOCKING else 0
RECHECK_COST_PER_SCENE = 0.6 + 0.35 * (GATE_READINGS - 1) + _BLOCKING_COST

#: Under `GATE_CHECK_METHOD` `questions` (#649) the open checker's readings
#: drop out of a gate run: extraction and persistence on sonnet ($0.13-0.19
#: a scene from two books' cost ledgers, #649's history; rounded up), the
#: question layer's four or five small-model calls (two askings of the
#: facts, a third of any they split on, two of the brief's promises: about
#: $0.001-0.01 a scene; rounded up) and the blocking check as above. A
#: forecast, not measured on a gated book
QUESTIONS_GATE_COST_PER_SCENE = 0.3 + 0.02 + _BLOCKING_COST

#: Under `tandem` (#738) a first run is the open checker's run and the
#: question layer's calls (as above, $0.02 rounded up). Every gate run a
#: forecast counts is priced as a first run: a re-check or `check
#: --pending` is one, and the re-checks after a fix (the question layer and
#: one small `questions.ask_resolved` call, about $0.01, in place of the
#: open readings) are inside `WRITE_GATE_FIX_SHARE`, which prices them at
#: a first run's share, so the forecast errs high there
TANDEM_GATE_COST_PER_SCENE = RECHECK_COST_PER_SCENE + 0.02


def recheck_cost_per_scene() -> float:
    """What one gate run is forecast to cost under the run's check method:
    `RECHECK_COST_PER_SCENE` for the open checker,
    `QUESTIONS_GATE_COST_PER_SCENE` for the questions,
    `TANDEM_GATE_COST_PER_SCENE` for both (#738) (read when called, so
    `check --questions`'s forecast and threshold stops price what it
    runs)."""
    return {'questions': QUESTIONS_GATE_COST_PER_SCENE,
            'tandem': TANDEM_GATE_COST_PER_SCENE}.get(GATE_CHECK_METHOD,
                                                      RECHECK_COST_PER_SCENE)


#: The share `write`'s forecast adds to a gate run for the fixes, their
#: re-gates and the partial-fix retry (`_partial_fix`), which run only on
#: the scenes that fail: a quarter more, an estimate, not measured
WRITE_GATE_FIX_SHARE = 1.25


def write_gate_cost_per_scene() -> float:
    """What `write`'s token-model forecast prices one drafted scene's gate at
    (#556's review): a gate run under the run's check method
    (`recheck_cost_per_scene()`, read when called, so `write --questions`
    prices the question layer), plus `WRITE_GATE_FIX_SHARE` for the fixes.
    The ledger-priced forecast (`costs.forecast_write`) counts what this
    book's gates actually cost, retries included."""
    return recheck_cost_per_scene() * WRITE_GATE_FIX_SHARE


#: A pending row's command for a scene listed for a re-check, and for one
#: whose re-check didn't pass (not re-run until the author acts:
#: `storyforge check --pending` or a redraft)
RECHECK, RECHECK_FAILED = 'recheck', 'recheck-failed'
#: A scene whose prose states a fact the author rejected: the author revises
#: it; when it passes the gate, the scenes depending on the rejection are
#: listed (its reason carries `[rejected: ids]`, kept by `mark_pending`)
REVISE_REJECTED = 'revise-rejected'


@dataclass
class Recheck:
    """`recheck_pending`'s answer."""
    passed: list[str] = field(default_factory=list)
    #: the scene that didn't pass, and why ('' when none failed)
    failed: str = ''
    why: str = ''
    result: GateResult | None = None
    #: the re-check scenes still pending when it stopped
    left: list[str] = field(default_factory=list)
    #: the forecast was over the cost threshold, so it stopped before a scene
    over_budget: bool = False
    forecast: float = 0.0
    #: `spent_before` plus this call's re-checks at their forecast: what the
    #: run has spent or reserved (`costs.RunBudget.committed`) once they ran
    spent: float = 0.0
    #: what the caller's run had spent and reserved before this call
    spent_before: float = 0.0
    #: what the re-checks that passed did not record, or recorded as new that
    #: reads like a kept fact (`reread_lines`), each `scene: line` (#599)
    notes: list[str] = field(default_factory=list)


def recheck_queue(project_dir: str, skip: set[str] | frozenset[str] = frozenset()) -> list[str]:
    """The scenes pending a re-check (`RECHECK`, not `RECHECK_FAILED`), in
    reading order, without `skip`."""
    order = ledger.scene_order(project_dir)
    return sorted((s for s, r in pending(project_dir).items()
                   if r['command'] == RECHECK and s not in skip and s in order),
                  key=order.get)


def recheck_pending(project_dir: str, *, log_dir: str, skip: set[str] | frozenset[str] = frozenset(),
                    spent_before: float = 0.0, extract_model: str | None = None,
                    check_model: str | None = None) -> Recheck:
    """Re-gate the scenes pending a re-check (design §3), one at a time in
    reading order, never editing their prose: each one's commitments are
    extracted again against the ledger as it now is, checked, and committed
    when clean, which may list later scenes in turn (the cascade only moves
    forward: a scene lists only scenes after it). Stops at the first scene
    that doesn't pass, listed `RECHECK_FAILED` with the reason so it isn't
    re-run until the author acts (Ben, 2026-10-31: report and stop); the
    rest stay pending. `skip` is scenes the caller will gate itself (its
    redrafts, the rest of a pass, or scenes a later pass of its plan
    rewrites, #619). A scene whose first run only the extractor's slips
    stopped is gated once more (`gate_unchanged`, #620) when the threshold
    allows it, a second run added to `.spent`.

    Cost (Ben: forecast, and run under the threshold): the forecast is
    logged first; before each scene, `spent_before` plus this call's spend
    plus the queue left at `recheck_cost_per_scene()` must be within
    `costs.check_threshold`, otherwise it stops with `over_budget` and
    everything stays pending for `storyforge check --pending`. The
    threshold is one budget for the caller's whole run (`costs.RunBudget`):
    `spent_before` is what the run has spent so far, drafting and gating
    included, plus what it reserves for the work it still owes, so the
    re-checks get only what is left."""
    from storyforge.common import log
    from storyforge.costs import check_threshold, cost_threshold
    run = Recheck(spent=spent_before, spent_before=spent_before)
    announced = False
    while True:
        queue = recheck_queue(project_dir, skip)
        if not queue:
            return run
        run.forecast = run.spent + len(queue) * recheck_cost_per_scene()
        if not check_threshold(run.forecast):
            run.over_budget, run.left = True, queue
            log(f'WARNING: re-checking {len(queue)} scene(s) ({", ".join(queue[:8])}) would '
                f'bring this run to about ${run.forecast:.2f} (${run.spent_before:.2f} of it '
                f'spent or owed before the re-checks), over the cost threshold '
                f'(${cost_threshold():g}): not run. They stay in {PENDING_PATH}; run '
                f'`{pending_command()}` (with STORYFORGE_COST_THRESHOLD raised if '
                f'needed).')
            return run
        if not announced:
            log(f'Re-checking {len(queue)} scene(s) whose facts depend on what changed, '
                f'forecast about ${len(queue) * recheck_cost_per_scene():.2f}: {", ".join(queue)}')
            announced = True
        sid = queue[0]
        # #632: why it was listed, so a cascade's cause is in the log
        listed = (pending(project_dir).get(sid) or {}).get('reason', '')
        log(f'Re-checking {sid}...' + (f' ({_one_line(listed)[:300]})' if listed else ''))
        run.spent += recheck_cost_per_scene()   # paid whether or not it finishes
        try:
            logs = run_log_dir(os.path.join(log_dir, 'recheck'), sid)
            log(f'  logs: {os.path.relpath(logs, project_dir)}')
            left = len(recheck_queue(project_dir, skip)) - 1
            result, reextraction = gate_unchanged(
                project_dir, sid, command='recheck', log_dir=logs,
                extract_model=extract_model, check_model=check_model,
                introduced_by=_writer(project_dir, sid),
                afford=lambda: check_threshold(
                    run.spent + (1 + left) * recheck_cost_per_scene()))
        except GateError as e:
            why = ' '.join(str(e).split())
            mark_pending(project_dir, sid, RECHECK_FAILED, f're-check could not run: {why}')
            run.failed, run.why, run.left = sid, why, recheck_queue(project_dir, skip)
            return run
        if reextraction is not None:
            if not reextraction.error.startswith('not run'):
                run.spent += recheck_cost_per_scene()   # the re-extraction is a second run
            log(f'  {sid}: {reextraction.summary()}')
        if not result.passed:
            lines = blocking_lines(report_lines(result))
            said = f' ({reextraction.summary()})' if reextraction is not None else ''
            mark_pending(project_dir, sid, RECHECK_FAILED,
                         f're-check did not pass: {len(lines)} problem(s): '
                         + '; '.join(_one_line(x) for x in lines[:3]) + said)
            run.failed, run.why, run.result = sid, '; '.join(lines[:3]) + said, result
            run.left = recheck_queue(project_dir, skip)
            return run
        run.passed.append(sid)
        # #622's review (SF-H2): what a re-check applied and reported (a
        # moved end, an id read without its prefix) reaches the caller's log
        run.notes += [f'{sid}: {line}' for line in reread_lines(result) + applied_lines(result)]


def _writer(project_dir: str, scene_id: str) -> str:
    """The command that wrote `scene_id`'s prose, as its commitments record
    it (the most common), so a re-check keeps it; `recheck` when none do."""
    from collections import Counter
    writers = Counter((r.get('introduced_by') or '').strip() for r in ledger.load(project_dir)
                      if ledger.is_commitment(r) and (r.get('scene_id') or '').strip() == scene_id)
    return writers.most_common(1)[0][0] if writers else 'recheck'
