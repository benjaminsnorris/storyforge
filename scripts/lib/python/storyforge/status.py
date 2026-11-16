"""storyforge status — deterministic next-step verdict.

Composes the existing floor / consistency / coverage scorers plus phase and
scene draft-state into a single routable verdict: where the project sits on
the elaboration ladder and the single recommended next action.

No LLM, no writes. Pure over project files.
"""

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, TypedDict

from storyforge.scoring_levels import (
    LEVEL_NAMES, blocking_failed, counts_against_rung, is_advisory_failure, score_all_levels,
)
from storyforge.scoring_consistency import score_consistency_all_levels
from storyforge.scoring_coverage import score_coverage_all_levels
from storyforge.common import (
    MEDIUM_GRAPHIC_NOVEL, VOICE_STAGE, VOICE_STAGE_COMMAND,
    parse_story_summary, read_yaml_field,
)
from storyforge.elaborate import _read_csv
from storyforge.adaptation import GIVEN_LEVELS

if TYPE_CHECKING:
    from storyforge import voice_book

LADDER_LEVELS = [0, 1, 2, 3, 4, 5, 6]
PROSE_STAGES = ('logline', 'synopsis', 'act-shape')

# Closed sets, mirrored in the skill/CLI docs — express them as Literals (as
# scoring_levels.py does for its result shapes) so drift is visible in-type.
RungState = Literal['solid', 'thin', 'not_started', 'given']
Stage = Literal['logline', 'synopsis', 'act-shape', 'spine', 'architecture',
                'scene-map', 'briefs', 'story-power', 'voice', 'draft', 'evaluate',
                'check', 'interpretation']

#: A rung that holds the next one up: built and solid, or (#658) given by an
#: adaptation's source and its interpretation decisions
DONE_STATES: tuple[RungState, ...] = ('solid', 'given')

# Rung name -> `elaborate --stage` argument (only rungs with a command stage).
ELABORATE_STAGE = {
    'spine': 'spine',
    'architecture': 'architecture',
    'scene-map': 'map',
    'briefs': 'briefs',
}

# The voice rung (#596, moved up by #656): a prose book's voice
# (`voice_book.resolve`: reference/voice/book.md and an anchor, or an author
# voice repo). Not a floor-checked ladder level; the verdict's `voice` record,
# shown between L2 and L3 by default, after L6 with `voice_stage: later`.
# Where it sits (`voice_book.stage_setting`):
#
# - `first` (the default, plan decision 12): once the prose tier is solid
#   and before drafting, a book without its voice gets `voice` as the phase
#   and `next`, the rung it would build as `then`. Who tells the story, and
#   from how far, decides which scenes exist and whose eyes they're in. A
#   soft default: `voice_stage: later` in key-decisions.md does structure
#   first.
# - `later`: the voice waits for drafting, as before #656, and the check
#   after the map is only ever a NOTE.
# - Either way, drafting without it is a `voice` blocker (the phase and
#   `next` before drafting, or `then` while scenes wait on the gate; once
#   every scene is drafted, the blocker alone).
# - The short second check after the map: with the voice found and the map
#   solid, a POV of the map's that book.md says nothing of
#   (`voice_book.pov_gaps`) makes `voice` the phase and `next` before any
#   brief is written or scene drafted (CR-2: not merely while the briefs
#   rung is thin), and a NOTE otherwise.
#
# A graphic novel's script has its own voice files, so it has no voice rung.

#: the structural rungs the voice comes before by default (#656)
_BEFORE_VOICE_FIRST = ('spine', 'architecture', 'scene-map', 'briefs')

#: the voice record's states: a rung's, and 'unreadable' (a file or the
#: `voice:` block can't be read)
VoiceState = Literal['solid', 'thin', 'not_started', 'unreadable']


class VoiceRecord(TypedDict):
    """The verdict's `voice` (#656). `pov_gaps`: the POVs of the map book.md
    says nothing of, `[]` when the check after the map ran clean, None when
    it didn't run (no voice, no solid map, or a file it couldn't read)."""
    name: str
    state: VoiceState
    detail: str
    when: 'voice_book.VoiceStage'
    pov_gaps: list[str] | None


class PlanGapRecord(TypedDict):
    """One gap of the two-writers test (#657, `bibles.Gap`) in `--json`."""
    kind: str
    ref: str
    subject: str
    detail: str


class PlanGapsRecord(TypedDict):
    """The verdict's `plan_gaps` (#702): the gaps the two-writers test sees
    in the plan (`bibles.plan_gaps`, the list `validate` and the stage
    reviews show), and what it couldn't check. Advisory: a plan may leave
    a question open on purpose, so a gap never blocks and never routes."""
    gaps: list[PlanGapRecord]
    notes: list[str]


def plan_gaps_record(project_dir: str) -> PlanGapsRecord:
    """`bibles.plan_gaps` as the verdict's record. Its notes say what it
    couldn't read (a ledger not migrated, a registry, the briefs), so an
    empty `gaps` with no notes means checked and clean."""
    from storyforge import bibles
    gaps, notes = bibles.plan_gaps(os.path.join(project_dir, 'reference'))
    return {'gaps': [{'kind': g.kind, 'ref': g.ref, 'subject': g.subject, 'detail': g.detail}
                     for g in gaps],
            'notes': list(notes)}


def _book_text(project_dir: str) -> str:
    """book.md's text ('' when missing, empty, the template or unreadable:
    an unreadable one is said by `resolve`)."""
    from storyforge import voice_book
    from storyforge.common import ReferenceDocError
    try:
        return voice_book.read_folder(project_dir).notes
    except ReferenceDocError:
        return ''

#: what status recommends for drafting (Storyforge's unattended drafting
#: passes --keep-going, Ben 2026-11-04)
#: a prose book is drafted in long writing sessions (#655; Ben, 2026-11-14):
#: one writer, the voice and the story so far in context. A session commits
#: provisionally as --keep-going does
WRITE_COMMAND = 'storyforge write --session'
#: a graphic novel's script is drafted scene by scene
GN_WRITE_COMMAND = 'storyforge write --keep-going'


def write_command(medium: str = 'novel') -> str:
    """What status recommends for drafting a book of `medium`."""
    return GN_WRITE_COMMAND if medium == MEDIUM_GRAPHIC_NOVEL else WRITE_COMMAND
#: what clears scenes waiting on the gate; `next.stage` 'check' while any
#: wait, unless write can still draft a scene past them (#641)
CHECK_COMMAND = 'storyforge check --pending'

# Which reference CSV backs each structural rung.
_LEVEL_CSV = {
    3: 'spine.csv',
    4: 'architecture.csv',
    5: 'scenes.csv',
    6: 'scene-briefs.csv',
}

# Prose-tier level -> parse_story_summary key.
_PROSE_KEY = {0: 'logline', 1: 'synopsis', 2: 'act_shape'}


def artifact_present(project_dir: str, level: int) -> bool:
    """True when the artifact backing `level` exists with real content."""
    if level in _PROSE_KEY:
        parsed = parse_story_summary(project_dir)
        if parsed is None:
            return False
        return bool(parsed.get(_PROSE_KEY[level], '').strip())
    path = os.path.join(project_dir, 'reference', _LEVEL_CSV[level])
    # Presence means "at least one data row with real content" — read through
    # the same DictReader-backed parser the floor checks use so a short/ragged
    # row is counted (not silently dropped) and a delimiter-only blank row
    # ("|||") does not masquerade as content. Missing file → [] → False.
    rows = _read_csv(path)
    # Guard `isinstance(v, str)`: a ragged row with more fields than headers
    # lands the overflow under DictReader's None restkey as a list, which we
    # must not .strip() (and which never counts as real content anyway).
    return any(isinstance(v, str) and v.strip()
               for row in rows for v in row.values())


#: The `source` of each `advisory` record from a craft-framework floor
#: check (#643), so consumers tell them from the gate's broken promises
#: (whose `source` is a fact id or a scene id, never with a space) by a
#: field, not a string prefix (#643's review TD-2)
CRAFT_ADVISORY_SOURCE = 'craft framework'


def _real_failed(floor: dict) -> int:
    """Floor failures that keep a rung thin: not accepted by the author via
    override, and not advisory (a craft-framework check, #643)."""
    return blocking_failed(floor)


def craft_advisory(floors: list[dict]) -> list[dict[str, str]]:
    """#643: the failed craft-framework floor checks (value shift, turning
    point, action/sequel balance) of the
    rungs in `floors` (the caller passes those whose artifact is present),
    one record each, in `gate.read_advisory`'s shape: `scene_id` '' (a floor
    check is book-wide; its `finding` names the first scene), `command` the
    `storyforge score --level N` that lists every scene, `source`
    `CRAFT_ADVISORY_SOURCE`, `quote` '', `finding` `L<n> <rung>: <check>
    (<detail>)`, `stale` ''. Reported, never blockers and never the next
    step: a scene needn't fit a framework."""
    return [{'scene_id': '', 'command': f"storyforge score --level {r['level']}",
             'source': CRAFT_ADVISORY_SOURCE, 'quote': '',
             'finding': (f"L{r['level']} {r['name']}: {c['check']}"
                         + (f" ({c['detail']})" if c.get('detail') else '')),
             'stale': ''}
            for r in floors for c in r['checks'] if is_advisory_failure(c)]


def ladder_states(project_dir: str, medium: str = 'novel',
                  floors: list[dict] | None = None) -> list[dict]:
    """Return per-rung state for levels 0-6, derived from floor checks only.

    Coverage/consistency are NOT folded in here — they look downstream and
    would wrongly keep an upstream rung `thin`; they surface as blockers.
    Advisory (craft-framework) floor checks don't either (#643). `floors`
    is `score_all_levels`' answer when the caller already has it.
    """
    if floors is None:
        floors = score_all_levels(project_dir, medium)
    floors = {r['level']: r for r in floors}
    ladder = []
    for level in LADDER_LEVELS:
        floor = floors[level]
        if not artifact_present(project_dir, level):
            state, detail = 'not_started', ''
        elif _real_failed(floor) == 0:
            state, detail = 'solid', ''
        else:
            state = 'thin'
            fails = [c['detail'] or c['check'] for c in floor['checks']
                     if counts_against_rung(c)]
            detail = fails[0] if fails else ''
        ladder.append({'level': level, 'name': LEVEL_NAMES[level],
                       'state': state, 'detail': detail})
    return ladder


# Scene statuses that count as drafted-or-later.
_DRAFTED_STATUSES = {'drafted', 'polished'}
from storyforge.schema import INACTIVE_STATUSES as _EXCLUDED_STATUSES  # noqa: E402

# yaml / legacy phase names normalized onto the post-briefs ladder phases.
_PHASE_ALIASES = {
    'drafting': 'draft',
    'evaluation': 'evaluate',
    'revision': 'evaluate',
    'review': 'evaluate',
    'polish': 'evaluate',
    'production': 'evaluate',
    'complete': 'evaluate',
}

# Ladder index for each comparable phase name. Rungs keep their level (0-6);
# draft/evaluate both sit past briefs, so both require rungs 0-6 to be solid.
_PHASE_INDEX = {name: level for level, name in LEVEL_NAMES.items()}
_PHASE_INDEX['draft'] = 7
_PHASE_INDEX['evaluate'] = 7


def collect_blockers(project_dir: str) -> list[dict]:
    """Coverage + consistency failures for rungs whose artifact is present."""
    blockers: list[dict] = []
    for source, results in (
        ('coverage', score_coverage_all_levels(project_dir)),
        ('consistency', score_consistency_all_levels(project_dir)),
    ):
        for r in results:
            level = r['level']
            if not artifact_present(project_dir, level):
                continue
            for c in r['checks']:
                if not c['passed'] and not c.get('accepted'):
                    blockers.append({'source': source, 'level': level,
                                     'detail': c['detail'] or c['check']})
    seen = set()
    deduped = []
    for b in blockers:
        key = (b['source'], b['level'], b['detail'])
        if key not in seen:
            seen.add(key)
            deduped.append(b)
    return deduped


def _read_scene_statuses(project_dir: str) -> list[str]:
    """Scene `status` values from scenes.csv (missing file/rows → []).

    Uses the DictReader-backed reader (not a raw split) so a row too short to
    reach the `status` column is kept with an empty status rather than
    silently dropped — otherwise draft_stage would undercount scenes and could
    report a false "all drafted" verdict.
    """
    rows = _read_csv(os.path.join(project_dir, 'reference', 'scenes.csv'))
    return [r.get('status', '') for r in rows]


def draft_stage(project_dir: str) -> tuple[Stage, int, int]:
    """Return (stage, drafted, total) for the post-briefs rungs.

    stage is 'evaluate' once every non-cut/merged scene is drafted+; else
    'draft'. total counts scenes excluding cut/merged.
    """
    statuses = [s for s in _read_scene_statuses(project_dir)
                if s not in _EXCLUDED_STATUSES]
    total = len(statuses)
    drafted = sum(1 for s in statuses if s in _DRAFTED_STATUSES)
    if total > 0 and drafted == total:
        return 'evaluate', drafted, total
    return 'draft', drafted, total


def _recommend(stage: Stage, medium: str = 'novel') -> tuple[dict, dict | None]:
    """Map the current stage to (next, then) step objects."""
    if stage in PROSE_STAGES:
        level = {'logline': 0, 'synopsis': 1, 'act-shape': 2}[stage]
        nxt = {'stage': stage,
               'action': f'Develop the {stage} (elaborate skill, prose tier)',
               'command': f'storyforge score --level {level}',
               'reason': f'The {stage} floor is not yet met'}
        then = {'stage': 'story-power',
                'action': 'Pressure-test the pitch with the story-power scorecard',
                'command': 'storyforge score --story-power',
                'reason': 'Validate narrative design before building the spine'}
        return nxt, then
    if stage in ELABORATE_STAGE:
        order = list(ELABORATE_STAGE)
        nxt = {'stage': stage,
               'action': f'Develop the {stage}',
               'command': f'storyforge elaborate --stage {ELABORATE_STAGE[stage]}',
               'reason': f'{stage} is the next incomplete rung'}
        i = order.index(stage)
        if i + 1 < len(order):
            nxt_name = order[i + 1]
            then = {'stage': nxt_name,
                    'action': f'Develop the {nxt_name}',
                    'command': f'storyforge elaborate --stage {ELABORATE_STAGE[nxt_name]}',
                    'reason': ''}
        else:
            then = {'stage': 'draft', 'action': 'Draft scenes',
                    'command': write_command(medium), 'reason': ''}
        return nxt, then
    if stage == VOICE_STAGE:
        return ({'stage': VOICE_STAGE, 'action': 'Find the voice',
                 'command': VOICE_STAGE_COMMAND,
                 'reason': ('Briefs are complete; drafting needs the voice: '
                            'reference/voice/book.md and an anchor passage (see the voice '
                            'blocker)')},
                {'stage': 'draft', 'action': 'Draft scenes',
                 'command': write_command(medium), 'reason': ''})
    if stage == 'interpretation':
        # #658: an adaptation entering at the scene map, before its source
        # gives the upper rungs. A fallback: `build_status` takes the step
        # `AdaptationRoute.verdict` builds (the same helper, with what's
        # missing) and the step after it from the voice
        return interpretation_step(), _recommend('scene-map', medium)[0]
    if stage == 'draft':
        return ({'stage': 'draft', 'action': 'Draft scenes',
                 'command': write_command(medium),
                 'reason': 'Briefs are complete; scenes are ready to draft'},
                {'stage': 'evaluate', 'action': 'Evaluate drafted scenes',
                 'command': 'storyforge evaluate', 'reason': ''})
    if stage == 'evaluate':
        return ({'stage': 'evaluate', 'action': 'Evaluate and polish',
                 'command': 'storyforge evaluate',
                 'reason': 'All scenes are drafted'}, None)
    # Fail loud rather than silently returning "go evaluate" for an unknown
    # stage — guards the PROSE_STAGES / ELABORATE_STAGE / LEVEL_NAMES invariant
    # (which is mirrored by hand and could drift, e.g. the scene-map↔map
    # spelling) instead of shipping a wrong verdict.
    raise ValueError(f'_recommend: unrecognized stage {stage!r}')


def voice_step(kind: str, detail: str = '', gaps: list[str] | tuple = ()) -> dict:
    """#656: the voice stage's `next` before drafting. `kind` 'first' (the
    voice isn't found yet, and comes before the structure deepens; `detail`
    says what's missing) or 'check' (the short check after the map: `gaps`
    are the POVs book.md says nothing of)."""
    from storyforge import voice_book
    if kind == 'first':
        return {'stage': VOICE_STAGE, 'action': 'Find the voice',
                'command': VOICE_STAGE_COMMAND,
                'reason': (f'{detail}. The voice comes before the spine and architecture '
                           f'deepen: who tells the story, and from how far, decides which '
                           f'scenes exist and whose eyes they\'re in. Find it by sample '
                           f'rounds (`storyforge voice sample --moment "..."` before the map). '
                           f'To build the structure first, put `{voice_book.STAGE_KEY}: '
                           f'{voice_book.STAGE_LATER}` in {voice_book.KEY_DECISIONS}')}
    if kind == 'check':
        return {'stage': VOICE_STAGE, 'action': 'Check the voice against the map',
                'command': VOICE_STAGE_COMMAND,
                'reason': (f'The map is done; {voice_book.BOOK_FILE} says nothing of '
                           f'{len(gaps)} POV(s): {", ".join(gaps)}. Say how each one\'s '
                           f'scenes are told (who, how close, the tense), so the voice holds '
                           f'across the POV mix, before the briefs')}
    raise ValueError(f'voice_step: unrecognized kind {kind!r}')


def gate_waiting(project_dir: str) -> list[dict[str, str]]:
    """The rows of working/gate-pending.csv, in reading order where known
    (an unreadable file is one row saying so)."""
    from storyforge import gate, ledger
    try:
        rows = gate.pending(project_dir)
    except gate.GateError as e:
        return [{'scene_id': gate.PENDING_PATH, 'command': 'unreadable', 'reason': str(e)}]
    try:
        order = ledger.scene_order(project_dir)
    except Exception:
        order = {}
    out = [rows[s] for s in sorted(rows, key=lambda s: (order.get(s, 10**9), s))]
    # #557: the scenes listed to fix toward the source (their own file)
    try:
        fixes = gate.source_fixes(project_dir)
    except gate.GateError as e:
        fixes = {gate.SOURCE_FIX_PATH: {'scene_id': gate.SOURCE_FIX_PATH, 'reason': str(e)}}
    out += [{'scene_id': s, 'command': 'source-fix', 'reason': fixes[s]['reason']}
            for s in sorted(fixes, key=lambda s: (order.get(s, 10**9), s))]
    return out


def gate_advisory(project_dir: str) -> tuple[list[dict[str, str]], list[str]]:
    """#642: the broken promises the gate reported but didn't stop on
    (`gate.read_advisory`, working/gate-advisory.csv), one record each
    (`{scene_id, command, source, quote, finding, stale}`), and what
    couldn't be read, one line each (a `gate` blocker, never a promise).
    Not blockers: the prose stands unless the author marks the beat
    `must:`."""
    from storyforge import gate
    found = gate.read_advisory(project_dir)
    return found.rows, found.problems


def free_to_draft(project_dir: str) -> tuple[int, int, list[str]]:
    """#641's review (CR-2, SF-3, T-1): (the scenes `write --keep-going`
    would draft, how many of them no scene waiting on the gate holds back,
    what couldn't be read), by write's own rule (`cmd_write.held_scenes`).
    What those read logs is caught, not printed (`--json` is the output),
    and returned for the verdict; anything that stops the reading is
    returned too, with (0, 0)."""
    import contextlib
    import io
    from storyforge import cmd_write
    from storyforge.prompts import get_scene_status
    from storyforge.scene_filter import build_scene_list
    said = io.StringIO()
    try:
        with contextlib.redirect_stdout(said):
            to_draft = [s for s in build_scene_list(
                os.path.join(project_dir, 'reference', 'scenes.csv'))
                if get_scene_status(s, project_dir) not in
                ('drafted', 'revised', 'final', 'unreadable')]
            held = cmd_write.held_scenes(project_dir, to_draft, keep_going=True)
    except (Exception, SystemExit) as e:   # status never fails on what it can't read
        return 0, 0, [line.split('] ', 1)[-1] for line in said.getvalue().splitlines()] \
            + [f'could not tell which scenes write can draft: {e or type(e).__name__}']
    notes = [line.split('] ', 1)[-1] for line in said.getvalue().splitlines()
             if 'WARNING' in line or 'ERROR' in line]
    return len(to_draft), len(to_draft) - len(held), notes


#: #658: what shows an adaptation's interpretation decisions and what's
#: missing, or why its `source:` block can't be used (`source status`);
#: `source import` while a source isn't imported
INTERPRETATION_COMMAND = 'storyforge source status'
IMPORT_COMMAND = 'storyforge source import'
INTERPRETATION_REASON = (
    "An adaptation's logline, synopsis, act shape, spine and architecture come from "
    "its source and the author's interpretation decisions in reference/key-decisions.md "
    "(what this version is about, whose eyes, what's cut, what's invented, where it "
    "ends, the mode); record them (elaborate skill)")
#: the coverage checks from a given rung down (act-shape to spine, spine to
#: architecture, architecture to scene map), not asked of a book entering
#: at the map: the rungs above the map are the source's
_GIVEN_COVERAGE_LEVELS = (2, 3, 4)
#: the `source` of the blockers an adaptation adds to `--json`: what keeps
#: its upper rungs from being given (level -1), and source coverage once
#: the scene map exists (level 5)
INTERPRETATION_BLOCKER = 'interpretation'
SOURCE_BLOCKER = 'source'


def interpretation_step(entry=None) -> dict:
    """#658: the `interpretation` stage's step. With `entry`
    (`adaptation.Entry`): fix an unusable `source:` block (`source status`
    shows why; `source import` would fail the same way), import the source,
    or record the decisions, with what's missing in the reason."""
    action, command = 'Record the interpretation decisions', INTERPRETATION_COMMAND
    reason = INTERPRETATION_REASON
    if entry is not None:
        if entry.config_error:
            action = "Fix storyforge.yaml's source: block"
        elif not entry.imported:
            action, command = 'Import the source', IMPORT_COMMAND
        if entry.problems:
            reason = f'{reason}. Missing: {"; ".join(entry.problems)}'
    return {'stage': 'interpretation', 'action': action, 'command': command,
            'reason': reason}


@dataclass(frozen=True)
class AdaptationVerdict:
    """#658: what an adaptation changes in the verdict, from
    `AdaptationRoute.verdict`: the `phase` (the ladder's, or
    'interpretation'), `next` (the interpretation step, else None:
    `_recommend`'s; the step after it comes from the voice, in
    `build_status`), `notes`, and `blockers(found)`."""
    phase: str
    next: dict | None
    notes: tuple[str, ...]
    #: the `interpretation` blockers (what keeps the rungs from being given)
    extra: tuple[dict, ...]
    #: the `source` blockers (source coverage once the map exists)
    coverage: tuple[dict, ...]
    enters_at_map: bool

    def blockers(self, found: list[dict]) -> list[dict]:
        """`found` (`collect_blockers`) without the coverage from a given
        rung down, for a book entering at the map, plus the adaptation's."""
        out = found
        if self.enters_at_map:
            out = [b for b in found if not (b['source'] == 'coverage'
                                            and b['level'] in _GIVEN_COVERAGE_LEVELS)]
        return [*self.extra, *out, *self.coverage]


class AdaptationRoute:
    """#658 (plan D8): how a `source:` book moves up the ladder. Made by
    `adaptation_route`, which marks the given rungs in the ladder; then
    `verdict(computed)` gives the adaptation's part of the verdict, once,
    as a frozen `AdaptationVerdict`. The voice before the map is #656's
    voice step, which sees the given rungs as done."""

    def __init__(self, project_dir: str, entry):
        self.project_dir = project_dir
        self.entry = entry

    def verdict(self, computed: str) -> AdaptationVerdict:
        entry = self.entry
        notes: list[str] = list(entry.decisions.notes) if entry.decisions else []
        coverage, said = self._source_coverage()
        notes += said
        if not entry.enters_at_map:
            notes.insert(0, 'this adaptation has a spine or architecture of its own, so it '
                            'builds its upper rungs as an original does (the full ladder)')
            return AdaptationVerdict(computed, None, tuple(notes), (), coverage, False)
        extra = tuple({'source': INTERPRETATION_BLOCKER, 'level': -1, 'detail': p}
                      for p in entry.problems)
        given = {LEVEL_NAMES[lvl] for lvl in GIVEN_LEVELS}
        if not entry.ready and computed in given:
            return AdaptationVerdict('interpretation', interpretation_step(entry),
                                     tuple(notes), extra, coverage, True)
        # Ready: the given rungs count as done, so the phase is the scene map
        # (or briefs), and #656's voice step puts the voice before it (by
        # default; `voice_stage: later` builds the map first), with the check
        # after the map before the briefs. Nothing of the adaptation's own.
        return AdaptationVerdict(computed, None, tuple(notes), extra, coverage, True)

    def _source_coverage(self) -> tuple[tuple[dict, ...], list[str]]:
        """Validate's source coverage once the scene map exists: its blocking
        findings as `source` blockers (in faithful mode a source scene left
        out or cut with no reason; in either mode a scene with no map row,
        a malformed row), a blocker when coverage couldn't be checked, and a
        note counting the advisory findings (`storyforge validate` lists
        them)."""
        if not artifact_present(self.project_dir, 5):
            return (), []
        from storyforge import source

        def blocker(detail: str) -> dict:
            return {'source': SOURCE_BLOCKER, 'level': 5, 'detail': detail}
        try:
            cfg = source.read_config(self.project_dir)
            result = source.check_coverage(self.project_dir, cfg) if cfg else None
        except Exception as e:   # status never fails on what it can't read
            return (blocker(f'source coverage not checked: {str(e) or type(e).__name__}'),), []
        if result is None:
            return (), []
        found = [blocker((f"{f['scene_id']}: " if f.get('scene_id') else '') + f['message'])
                 for f in result['findings'] if f.get('severity') == 'blocking']
        advisory = [f for f in result['findings'] if f.get('severity') != 'blocking']
        if not result.get('checked'):
            why = '; '.join(f['message'] for f in advisory) or 'see storyforge validate'
            found.append(blocker(f'source coverage not checked: {why}'))
            return tuple(found), []
        notes = ([f'{len(advisory)} advisory source-coverage finding(s), not blocking '
                  f'(`storyforge validate` lists them)'] if advisory else [])
        return tuple(found), notes


def adaptation_route(project_dir: str, ladder: list[dict]) -> AdaptationRoute | None:
    """#658: None without a `source:` block. Otherwise the book's route;
    when it enters at the scene map with its source imported and its
    interpretation decisions recorded, each upper rung (`GIVEN_LEVELS`)
    it hasn't written itself is marked `given` in `ladder` (one the author
    did write, a logline say, is judged as it stands)."""
    from storyforge import adaptation
    entry = adaptation.entry(project_dir)
    if entry is None:
        return None
    if entry.enters_at_map:
        for rung in ladder:
            if rung['level'] in GIVEN_LEVELS and rung['state'] == 'not_started':
                if entry.ready:
                    rung['state'] = 'given'
                    rung['detail'] = 'from the source and the interpretation decisions'
                elif entry.config_error:
                    rung['detail'] = "the source gives it once storyforge.yaml's source: block can be used"
                else:
                    rung['detail'] = ('the source gives it once the interpretation '
                                      'decisions are recorded')
    return AdaptationRoute(project_dir, entry)


def build_status(project_dir: str, medium: str = 'novel') -> dict:
    """Compose the full next-step verdict. Deterministic, read-only."""
    floors = score_all_levels(project_dir, medium)   # once (#643's review SF-7)
    ladder = ladder_states(project_dir, medium, floors)

    # Current phase = first rung that is not solid; if all solid, derive from
    # scene draft-state.
    # #658: an adaptation's upper rungs are given by its source (marks
    # them `given` in `ladder`)
    route = adaptation_route(project_dir, ladder)
    phase = None
    for rung in ladder:
        if rung['state'] not in DONE_STATES:
            phase = rung['name']
            break
    if phase is None:
        phase, _drafted, _total = draft_stage(project_dir)
    adapted = route.verdict(phase) if route is not None else None
    if adapted is not None:
        phase = adapted.phase

    # #596: briefs to drafting with no voice. Before drafting the voice
    # stage is the phase (next, or then while scenes wait on the gate); once
    # every scene is drafted only the blocker is reported, since evaluation
    # and revision read the voice too.
    # #656: by default the voice comes first, once the prose tier is solid,
    # with a short check after the map (the comment at _BEFORE_VOICE_FIRST).
    voice_blocker = None
    voice_record: VoiceRecord | None = None
    voice_next: dict | None = None
    notes: list[str] = []
    if medium != MEDIUM_GRAPHIC_NOVEL:
        from storyforge import voice_book
        from storyforge.common import ReferenceDocError
        from storyforge.voice_repo import VoiceError
        try:
            voice = voice_book.resolve(project_dir)
        except VoiceError as e:   # a bad `voice:` block is a blocker, not a crash
            voice = voice_book.DocState('unreadable', 'storyforge.yaml', str(e))
        if voice.skipped:
            notes.append(voice_book.skipped_warning(voice).removeprefix('WARNING: '))
        when, problem = voice_book.stage_setting(project_dir)
        if problem:
            notes.append(problem)
        found = voice.kind == 'ok'
        rung = {r['name']: r['state'] for r in ladder}
        # None: the check after the map didn't run (no voice, no map yet,
        # or it couldn't read a file, said in a note); [] ran and is clean
        gaps: list[str] | None = None
        if found and rung.get('scene-map') == 'solid':
            try:
                gaps = voice_book.pov_gaps(project_dir)
            except ReferenceDocError as e:
                notes.append(f'the voice check after the map could not run: {e}')
        if found and not _book_text(project_dir):
            # the author repo is the voice; book.md has no text of the book's
            notes.append(f'the voice comes from the author repo, but {voice_book.BOOK_FILE} has '
                         f'no text yet: the book\'s narrator stance, people and tense belong '
                         f'there (the architecture and map prompts follow the stance only '
                         f'from book.md, and the check after the map reads it)')
        voice_record = {
            'name': VOICE_STAGE,
            'state': ('solid' if found else 'not_started' if voice.kind == 'missing'
                      else 'unreadable' if voice.kind == 'unreadable' else 'thin'),
            'detail': '' if found else voice.detail,
            'when': when,
            'pov_gaps': gaps,
        }
        # CR-2: before the briefs means no brief written and no scene
        # drafted, not a briefs rung that's thin in a book already drafting
        _stage, drafted, _total = draft_stage(project_dir)
        pre_briefs = (phase == 'briefs' and rung.get('briefs') == 'not_started'
                      and not drafted)
        if phase in _BEFORE_VOICE_FIRST and not found and when == voice_book.STAGE_FIRST:
            voice_next = voice_step('first', voice.detail)
        elif gaps and pre_briefs and when == voice_book.STAGE_FIRST:
            voice_next = voice_step('check', gaps=gaps)
        elif gaps:
            notes.append(f'{voice_book.BOOK_FILE} says nothing of {len(gaps)} POV(s) of the '
                         f'map: {", ".join(gaps)}. Say how each one\'s scenes are told '
                         f'(the voice check after the map)')
        if phase in ('draft', 'evaluate') and not found:
            voice_blocker = {
                'source': VOICE_STAGE, 'level': -1,  # sentinel: not a ladder rung
                'detail': (f'{voice.detail}: drafting has no voice to follow, and write '
                           f'refuses to draft. To give it one, {voice_book.REMEDY}'),
            }
            if phase == 'draft':
                phase = VOICE_STAGE

    declared = (read_yaml_field('phase', project_dir) or '').strip()
    normalized = _PHASE_ALIASES.get(declared, declared)
    # The declared yaml phase is a coarse milestone that legitimately LAGS the
    # fine-grained ladder — by convention `phase: drafting` stays put through
    # evaluation and revision, and no command advances it past `drafting`. So
    # we do NOT require declared == computed (that would fire a spurious
    # blocker on every post-drafting project). We flag only a real
    # contradiction: the declared phase claims progress whose prerequisites
    # aren't met — some ladder rung UPSTREAM of the declared phase is not solid
    # (e.g. "phase: architecture" while spine is still thin). A declared phase
    # on an all-not_started project is init intent (new projects default to
    # phase: spine), and an unrecognized/pre-spine phase (development,
    # scene-design, '') isn't comparable — both count as matching.
    declared_idx = _PHASE_INDEX.get(normalized)
    all_not_started = all(r['state'] == 'not_started' for r in ladder)
    if not declared or all_not_started or declared_idx is None:
        matches, unmet = True, []
    else:
        unmet = [r for r in ladder
                 if r['level'] < declared_idx and r['state'] not in DONE_STATES]
        matches = not unmet

    blockers = collect_blockers(project_dir)
    if adapted is not None:
        blockers = adapted.blockers(blockers)
        notes.extend(adapted.notes)
    if voice_blocker:
        blockers.insert(0, voice_blocker)
    if medium != MEDIUM_GRAPHIC_NOVEL:
        # the pipeline's voice files, ignored since reference/voice/: a note
        # (they block nothing), never deleted (the author's text)
        from storyforge import voice_book
        old = voice_book.old_files_note(project_dir)
        if old:
            notes.append(old)
    if declared and not matches:
        names = ', '.join(r['name'] for r in unmet)
        blockers.insert(0, {
            'source': 'phase', 'level': -1,  # sentinel: not a ladder rung
            'detail': (f"storyforge.yaml phase is '{declared}' but upstream "
                       f"rung(s) not yet solid: {names}"),
        })

    nxt, then = _recommend(phase, medium)
    if adapted is not None and adapted.next is not None:
        # the step after it: the voice when #656's voice step would come
        # before the map (no voice yet, `voice_stage` not later), else the map
        nxt = adapted.next
        then = (voice_step('first', voice_record['detail'])
                if voice_record is not None and voice_record['state'] != 'solid'
                and voice_record['when'] == 'first'
                else _recommend('scene-map', medium)[0])
    if voice_next:
        # the voice before the rung it would build (#656)
        phase, nxt, then = VOICE_STAGE, voice_next, nxt
    # #556's review: scenes waiting on the gate (a provisional commit from
    # `write --keep-going` among them) are blockers, and come before the
    # next rung, except while write can draft a scene (#641): it drafts past
    # them, holding back only the scenes that depend on one, so drafting
    # stays next and the check comes after it. When every scene left to
    # draft is held, write would draft nothing: the check comes first
    # (#641's review, CR-2)
    waiting = gate_waiting(project_dir)
    for row in waiting:
        blockers.append({'source': 'gate', 'level': -1,
                         'detail': f"{row['scene_id']} ({row['command']}): {row['reason']}"})
    if waiting:
        provisional = sum(r['command'] == 'provisional' for r in waiting)
        listed = (f'{len(waiting)} scene(s) in working/gate-pending.csv'
                  + (f', {provisional} committed provisionally' if provisional else ''))
        # its own stage (TD-6): forge routes on next.stage, and any other
        # next stage (voice, evaluate, ...) would send it to that work
        # instead; only draft keeps `next`, while write can draft (#641)
        check = {'stage': 'check', 'action': 'Clear the scenes waiting on the gate',
                 'command': CHECK_COMMAND,
                 'reason': f'{listed}: fix them (or `storyforge check --accept`), then check'}
        left, free, unread = (free_to_draft(project_dir) if nxt['stage'] == 'draft'
                              else (0, 0, []))
        for note in unread:   # what couldn't be read is said, not passed over
            blockers.append({'source': 'gate', 'level': -1, 'detail': note})
        if nxt['stage'] == 'draft' and (free or not left):
            nxt = dict(nxt, reason=(f'{nxt["reason"]}; {listed} (the gate blockers): write '
                                    f'drafts past them, holding back only the scenes that '
                                    f'depend on one'
                                    + (f' ({free} of {left} left to draft can be drafted '
                                       f'now)' if left else
                                       ' (could not tell which scenes it can draft'
                                       + ('; see the blockers)' if unread else ')'))))
            then = check
        else:
            if nxt['stage'] == 'draft':
                check = dict(check, reason=(f'{check["reason"]}: every one of the {left} '
                                            f'scene(s) left to draft waits on one of them, '
                                            f'so write would draft nothing'))
            then, nxt = nxt, check
    advisory, unread = gate_advisory(project_dir)
    for note in unread:   # a file that can't be read is said, not listed as a promise
        blockers.append({'source': 'gate', 'level': -1, 'detail': note})
    return {
        'phase': phase,
        'phase_declared': declared,
        'phase_matches_yaml': matches,
        'ladder': ladder,
        # #656: the voice (`VoiceRecord`), between the prose tier and the
        # spine by default, after the briefs with `voice_stage: later`; None
        # for a graphic novel
        'voice': voice_record,
        'next': nxt,
        'then': then,
        'blockers': blockers,
        # what the author should know that blocks nothing: old voice files
        # no longer read, anchors left out of the voice
        'notes': notes,
        # one list of records, never blockers (#642): the gate's broken
        # promises, then the craft-framework floor checks of rungs that
        # exist (#643, `source` CRAFT_ADVISORY_SOURCE)
        'advisory': advisory + craft_advisory(
            [f for f in floors if artifact_present(project_dir, f['level'])]),
        # #702: the two-writers test's gaps in the plan (`PlanGapsRecord`),
        # advisory like `validate`'s and the stage reviews'
        'plan_gaps': plan_gaps_record(project_dir),
    }
