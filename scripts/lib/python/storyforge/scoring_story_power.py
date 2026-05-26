"""Story-power scorecard — 8 research-grounded craft axes scored on
pitch artifacts (logline + synopsis + theme, optional spine/architecture).

Distinct from craft scoring (prose-level) and structural validation
(CSV-mechanical). Answers: if this story were rendered with adequate
prose, is it built to last?

See references/story-power-rubric.md for the full axis definitions,
research basis, signals, and worked example.
"""

import json
import os
import re
from datetime import datetime, timezone
from typing import Literal, NamedTuple, TypedDict

from storyforge.api import (
    invoke_to_file, calculate_cost_from_usage, extract_usage,
)
from storyforge.common import (
    CoachingLevel, get_plugin_dir, log, parse_story_summary,
    read_yaml_field, select_model,
)
from storyforge.costs import log_operation


# Type-narrow the weight: the rubric defines only two values. A drift to
# 1.25 / 2.0 would shift the composite math silently — catch it at import.
Weight = Literal[1.0, 1.5]

# Status values used by score_story_power's result. 'ok' covers every
# happy path (full scorecard, coach brief, strict checklist); the rest
# name a specific failure or short-circuit so callers can branch on the
# field instead of substring-matching a free-form mode string.
StoryPowerStatus = Literal[
    'ok',           # full scorecard / coach brief / strict checklist written
    'partial',      # LLM scored, but one or more axes missing / out-of-range
    'unparseable',  # LLM returned content but parse failed
    'llm_error',    # invoke_to_file raised
    'dry_run',      # dry-run preview only; no work done
    'no_api_key',   # full/coach with ANTHROPIC_API_KEY unset
    'no_rubric',    # full/coach with references/story-power-rubric.md missing
    'no_input',     # logline and/or synopsis missing
]


# Act keys form a closed three-act schema; expressing them as a Literal
# lets consumers static-check `per_act_scores['act2']` access patterns
# instead of relying on runtime KeyError.
ActKey = Literal['act1', 'act2', 'act3']


class ActShapeExtension(TypedDict):
    """The Layer 1 + Layer 2 payload that lands when act-shape mode runs.

    Presence on StoryPowerResult signals that the per-act matrix and
    structural axes are populated; consumers should branch on
    `result['act_shape'] is None` rather than a separate boolean.
    """
    per_act_scores: dict[ActKey, dict[str, int]]
    structural_axis_scores: dict[str, int]
    structural_diagnostic: dict
    status: StoryPowerStatus


class WeakHandoff(TypedDict):
    """A flagged causal-handoff transition. is_act_bridge is a heuristic
    (keyword match on the upstream's function — see _identify_weak_handoffs)."""
    from_event: str
    to_event: str
    score: int
    is_act_bridge: bool


class WholeSpineScores(TypedDict, total=False):
    """Closed-key Layer 2 axis scores. total=False because partial
    extraction is acceptable (missing axes surface in the partial-WARN)."""
    function_coverage: int
    escalation_curve: int
    arc_visibility: int
    thematic_distribution: int
    spine_act_shape_alignment: int


class SpineDiagnostic(TypedDict, total=False):
    """LLM-provided cross-axis pattern + high-leverage move at the spine
    resolution. total=False because the LLM may omit fields."""
    lowest_axis: str
    lowest_axis_average: str   # the LLM returns this as a decimal string
    summary: str
    high_leverage_move: str


Severity = Literal['high', 'medium', 'low']


class _ProposedFixRequired(TypedDict):
    target_handoff: str
    proposed_clause: str


class ProposedFix(_ProposedFixRequired, total=False):
    """One concrete clause-level bridge for the highest-leverage weak
    handoff. target_handoff and proposed_clause are required (extractor
    drops rows missing either); the rest are LLM-optional."""
    target_event_id: str
    current_summary_tail: str
    expected_lift: str


class SpineExtension(TypedDict):
    """Spine-mode payload (per-event + whole-spine scores, weak-handoff
    list, and the LLM's proposed clause-level fix)."""
    per_event_scores: dict[str, dict[str, int]]
    whole_spine_scores: WholeSpineScores
    spine_diagnostic: SpineDiagnostic
    weak_handoffs: list[WeakHandoff]
    proposed_fix: ProposedFix
    status: StoryPowerStatus


class WholeArchitectureScores(TypedDict, total=False):
    """Closed-key Layer 2 architecture axis scores."""
    action_sequel_rhythm: int
    spine_coverage_balance: int
    cumulative_arc_gradient: int
    scene_causal_chain: int
    scene_promise_payoff: int


class FieldCoherenceFinding(TypedDict):
    """A scene-level field-coherence problem flagged by the deterministic
    pre-pass or the LLM."""
    scene_id: str
    field: str
    issue: str
    severity: Severity


class _ProposedFieldUpdateRequired(TypedDict):
    scene_id: str
    field: str
    proposed_value: str


class ProposedFieldUpdate(_ProposedFieldUpdateRequired, total=False):
    """A concrete field-level fix the diagnostic proposes. scene_id,
    field, and proposed_value are required (extractor drops rows
    missing any); current_value and rationale are LLM-optional."""
    current_value: str
    rationale: str


class _ProposedSceneInsertionRequired(TypedDict):
    insert_after: str
    proposed_id: str
    summary: str


class ProposedSceneInsertion(_ProposedSceneInsertionRequired, total=False):
    """A new sequel scene proposed to deliver a spine bridge that no
    architecture scene enacts."""
    spine_event: str
    action_sequel: str
    emotional_arc: str
    value_at_stake: str
    value_shift: str
    turning_point: str
    rationale: str


class ArchitectureDiagnostic(TypedDict, total=False):
    """LLM-provided cross-axis pattern + register assessment."""
    lowest_axis: str
    lowest_axis_average: str
    summary: str
    register_assessment: str   # e.g., "73% action vs declared atmospheric register"
    high_leverage_move: str


class ArchitectureExtension(TypedDict):
    """Architecture-mode payload (Layer 1 + Layer 2 scores, field
    findings, and the LLM's proposed updates / insertions)."""
    per_scene_scores: dict[str, dict[str, int]]
    whole_architecture_scores: WholeArchitectureScores
    architecture_diagnostic: ArchitectureDiagnostic
    field_findings: list[FieldCoherenceFinding]
    proposed_field_updates: list[ProposedFieldUpdate]
    proposed_scene_insertions: list[ProposedSceneInsertion]
    status: StoryPowerStatus


class StoryPowerResult(TypedDict):
    """Result of score_story_power. Coaching is the requested level; status
    is the outcome. Output_dir is the timestamped directory written to
    (empty string when no directory was allocated).

    act_shape, spine, and architecture are None when their inputs
    weren't present (no `## Act-shape` populated, no spine.csv on disk,
    no architecture.csv on disk) or the extension failed before
    producing usable data; otherwise they carry the payload from each
    Layer 1/2 scoring run.
    """
    coaching: CoachingLevel
    status: StoryPowerStatus
    mode: str
    output_dir: str
    composite: float
    scores: dict[str, int]
    deltas: dict[str, int]
    diagnostic: dict
    act_shape: ActShapeExtension | None
    spine: SpineExtension | None
    architecture: ArchitectureExtension | None


class Axis(NamedTuple):
    key: str
    name: str
    weight: Weight


AXES: tuple[Axis, ...] = (
    Axis('specificity', 'Specificity & concreteness', 1.0),
    Axis('emotional_resonance', 'Emotional resonance', 1.0),
    Axis('character_identification', 'Character identification', 1.0),
    Axis('stakes_dilemma', 'Stakes & dilemma', 1.5),
    Axis('archetypal_resonance', 'Archetypal resonance', 1.5),
    Axis('thematic_depth', 'Thematic depth', 1.5),
    Axis('surprise_subversion', 'Surprise & genre subversion', 1.0),
    Axis('moral_weight', 'Moral weight', 1.5),
)
AXIS_KEYS = tuple(a.key for a in AXES)
AXIS_BY_KEY = {a.key: a for a in AXES}

# Module-load invariants. These guarantee the composite-weighting math
# downstream and catch drift the moment AXES is edited.
assert len({a.key for a in AXES}) == len(AXES), 'axis keys must be unique'
assert all(a.weight in (1.0, 1.5) for a in AXES), 'axis weights must be 1.0 or 1.5'
assert sum(1 for a in AXES if a.weight == 1.5) == 4, (
    'exactly four axes must carry the 1.5x weight per references/story-power-rubric.md'
)


class PitchArtifacts(NamedTuple):
    """The six pitch-tier artifacts the scorecard reads. Always returned
    with all six fields populated — empty strings stand in for absent
    inputs."""
    logline: str
    synopsis: str
    act_shape: str
    theme: str
    spine_summaries: str
    architecture_summaries: str


class ActShape(NamedTuple):
    """The three labeled paragraphs from `## Act-shape`.

    Only constructed via parse_act_shape, which guarantees all three
    bodies are non-empty. Treat any ActShape instance as already-validated.
    """
    act1: str
    act2: str
    act3: str


# Layer 2 structural axes — only meaningful at act-shape resolution.
STRUCTURAL_AXES: tuple[Axis, ...] = (
    Axis('causal_integrity', 'Causal integrity', 1.5),
    Axis('turning_point_clarity', 'Turning-point clarity', 1.5),
    Axis('arc_gradient', 'Arc gradient', 1.5),
    Axis('promise_payoff', 'Promise & payoff', 1.5),
)
STRUCTURAL_AXIS_KEYS = tuple(a.key for a in STRUCTURAL_AXES)
STRUCTURAL_AXIS_BY_KEY = {a.key: a for a in STRUCTURAL_AXES}

assert len({a.key for a in STRUCTURAL_AXES}) == len(STRUCTURAL_AXES), (
    'structural axis keys must be unique'
)
# Count invariant mirrors the pitch-axis style: pinning the *count* of
# 1.5x axes rather than asserting every axis is 1.5x leaves room for a
# future axis to land at 1.0 without crashing at import. Rubric documents
# four axes at 1.5x today; adjust here and in the rubric together.
assert sum(1 for a in STRUCTURAL_AXES if a.weight == 1.5) == 4, (
    'rubric documents four structural axes at 1.5x weight'
)
assert all(a.weight in (1.0, 1.5) for a in STRUCTURAL_AXES), (
    'structural axis weights must be 1.0 or 1.5'
)
assert not (set(AXIS_KEYS) & set(STRUCTURAL_AXIS_KEYS)), (
    'pitch axes and structural axes must have disjoint keys'
)


# Per-event axes (spine Layer 1). Causal handoff is the load-bearing
# axis at this resolution and carries the elevated weight.
PER_EVENT_AXES: tuple[Axis, ...] = (
    Axis('function_alignment', 'Function / summary alignment', 1.0),
    Axis('concreteness', 'Concreteness', 1.0),
    Axis('causal_handoff', 'Causal handoff', 1.5),
)
PER_EVENT_AXIS_KEYS = tuple(a.key for a in PER_EVENT_AXES)
PER_EVENT_AXIS_BY_KEY = {a.key: a for a in PER_EVENT_AXES}

# Whole-spine axes (spine Layer 2). The 1.5x-weighted pair (function
# coverage, escalation curve) is foundational; the other three are
# descriptive — see rubric §"Whole-spine axes".
SPINE_AXES: tuple[Axis, ...] = (
    Axis('function_coverage', 'Function coverage', 1.5),
    Axis('escalation_curve', 'Escalation curve', 1.5),
    Axis('arc_visibility', 'Arc visibility', 1.0),
    Axis('thematic_distribution', 'Thematic distribution', 1.0),
    Axis('spine_act_shape_alignment', 'Spine ↔ act-shape alignment', 1.0),
)
SPINE_AXIS_KEYS = tuple(a.key for a in SPINE_AXES)
SPINE_AXIS_BY_KEY = {a.key: a for a in SPINE_AXES}

assert len({a.key for a in PER_EVENT_AXES}) == len(PER_EVENT_AXES), (
    'per-event axis keys must be unique'
)
assert len({a.key for a in SPINE_AXES}) == len(SPINE_AXES), (
    'whole-spine axis keys must be unique'
)


# Per-scene axes (architecture Layer 1). Field coherence is the
# load-bearing axis — no other mode can detect summary↔field drift.
PER_SCENE_AXES: tuple[Axis, ...] = (
    Axis('spine_event_service', 'Spine-event service', 1.0),
    Axis('field_coherence', 'Field coherence', 1.5),
)
PER_SCENE_AXIS_KEYS = tuple(a.key for a in PER_SCENE_AXES)
PER_SCENE_AXIS_BY_KEY = {a.key: a for a in PER_SCENE_AXES}

# Whole-architecture axes (Layer 2). Action/sequel rhythm and scene
# causal chain carry the 1.5x weight — they're the ones that define
# whether a sequenced list of scenes feels like a story.
ARCHITECTURE_AXES: tuple[Axis, ...] = (
    Axis('action_sequel_rhythm', 'Action/sequel rhythm', 1.5),
    Axis('spine_coverage_balance', 'Spine coverage balance', 1.0),
    Axis('cumulative_arc_gradient', 'Cumulative arc gradient', 1.0),
    Axis('scene_causal_chain', 'Scene-level causal chain', 1.5),
    # Scene-level promise/payoff — distinct key from STRUCTURAL_AXES'
    # `promise_payoff` (which is the act-shape Layer 2 version of the
    # same rubric concept at a different resolution).
    Axis('scene_promise_payoff', 'Promise & payoff (scene)', 1.0),
)
ARCHITECTURE_AXIS_KEYS = tuple(a.key for a in ARCHITECTURE_AXES)
ARCHITECTURE_AXIS_BY_KEY = {a.key: a for a in ARCHITECTURE_AXES}

assert len({a.key for a in PER_SCENE_AXES}) == len(PER_SCENE_AXES), (
    'per-scene axis keys must be unique'
)
assert len({a.key for a in ARCHITECTURE_AXES}) == len(ARCHITECTURE_AXES), (
    'whole-architecture axis keys must be unique'
)
# Diagnostic routing identifies an axis's family from its key alone,
# which requires every family's keys to be disjoint. The data-driven
# loop below adds a new family in one line and reports *which* key
# collides between *which two* families on failure — no count math to
# keep in sync with the family list.
_AXIS_FAMILIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ('pitch', AXIS_KEYS),
    ('structural', STRUCTURAL_AXIS_KEYS),
    ('per_event', PER_EVENT_AXIS_KEYS),
    ('whole_spine', SPINE_AXIS_KEYS),
    ('per_scene', PER_SCENE_AXIS_KEYS),
    ('whole_architecture', ARCHITECTURE_AXIS_KEYS),
)
_axis_family_by_key: dict[str, str] = {}
for _family, _keys in _AXIS_FAMILIES:
    for _key in _keys:
        if _key in _axis_family_by_key:
            raise AssertionError(
                f'axis key {_key!r} appears in both '
                f'{_axis_family_by_key[_key]!r} and {_family!r} families; '
                'diagnostic routing requires disjoint keys across all axis '
                'families.'
            )
        _axis_family_by_key[_key] = _family
del _family, _keys, _key


# Function-class keywords for the function-appropriate concreteness
# floor. Quoted in the LLM prompt so the score reflects function fit,
# not absolute prose specificity (see rubric §"Function-appropriate
# floor").
CONCEPTUAL_SHIFT_FUNCTION_KEYWORDS = (
    'midpoint reversal', 'reversal', 'revelation', 'recognition',
    'discovery', 'realization', 'epiphany', 'reveal',
)


def function_concreteness_floor(function_text: str) -> Literal[7, 8]:
    """Return 7 for conceptual-shift functions, 8 otherwise."""
    f = (function_text or '').lower()
    if any(kw in f for kw in CONCEPTUAL_SHIFT_FUNCTION_KEYWORDS):
        return 7
    return 8


class SpineEvent(NamedTuple):
    """A single row from reference/spine.csv (id, title, summary, function only)."""
    id: str
    title: str
    summary: str
    function: str


class SceneRow(NamedTuple):
    """A single row from reference/architecture.csv carrying the columns
    architecture scoring consumes. Other columns (seq, part, pov, etc.)
    are read straight from the CSV when needed."""
    id: str
    title: str
    summary: str
    spine_event: str
    action_sequel: str
    emotional_arc: str
    value_at_stake: str
    value_shift: str
    turning_point: str


# Recognized register tokens for project.register (see rubric
# §"Action/sequel rhythm"). Literal narrowing on the return of
# read_project_register lets the prompt builder reason exhaustively.
Register = Literal[
    'thriller', 'action', 'fast', 'commercial',
    'literary', 'decompressed', 'atmospheric', 'contemplative',
    'balanced',
]
KNOWN_REGISTERS: tuple[Register, ...] = (
    'thriller', 'action', 'fast', 'commercial',
    'literary', 'decompressed', 'atmospheric', 'contemplative',
    'balanced',
)


def composite_score(scores: dict[str, int | float]) -> float:
    """Return the weighted composite from a {axis_key: score} dict.

    Computes a weighted average over the axes that are present (missing
    axes drop out of both numerator and denominator). Returns 0.0 when
    nothing is present. The caller decides whether a partial composite
    is meaningful; this never raises. Score range stays 1-10.
    """
    total_w = 0.0
    total = 0.0
    for axis in AXES:
        s = scores.get(axis.key)
        if s is None:
            continue
        total_w += axis.weight
        total += float(s) * axis.weight
    if total_w == 0:
        return 0.0
    return round(total / total_w, 2)


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------

def _read_optional(path: str, head_lines: int | None = None) -> str:
    if not os.path.isfile(path):
        return ''
    try:
        with open(path, encoding='utf-8') as f:
            text = f.read()
    except (OSError, UnicodeDecodeError):
        return ''
    if head_lines:
        lines = text.splitlines()
        if len(lines) > head_lines:
            text = '\n'.join(lines[:head_lines]) + '\n…'
    return text


def parse_act_shape(act_shape_body: str) -> ActShape | None:
    """Parse the body of `## Act-shape` into three labeled paragraphs.

    Expects `### Act 1` / `### Act 2` / `### Act 3` sub-headings. Returns
    None when act-shape mode is not available — body empty, fewer than
    three acts populated, or any act body is empty.

    Logs INFO when the body was *partially* populated (e.g. Act 1 only)
    so an author who almost made it doesn't silently fall back to
    pitch-only without knowing why.
    """
    if not act_shape_body.strip():
        return None
    parts = re.split(r'^###\s+Act\s+(\d+).*?$', act_shape_body,
                     flags=re.MULTILINE | re.IGNORECASE)
    acts: dict[int, str] = {}
    for i in range(1, len(parts), 2):
        try:
            n = int(parts[i])
        except ValueError:
            continue
        body = parts[i + 1].strip() if i + 1 < len(parts) else ''
        if 1 <= n <= 3:
            acts[n] = body
    populated = {n for n, body in acts.items() if body}
    if populated == {1, 2, 3}:
        return ActShape(act1=acts[1], act2=acts[2], act3=acts[3])
    if populated:
        missing = sorted({1, 2, 3} - populated)
        log(f'INFO: ## Act-shape is partially populated (missing Act '
            f'{", Act ".join(str(m) for m in missing)}). Running '
            'pitch-only; fill in the remaining act paragraph(s) to '
            'unlock per-act + structural scoring.')
    return None


def parse_spine(project_dir: str) -> list[SpineEvent]:
    """Read reference/spine.csv as an ordered list of SpineEvent.

    Returns [] when the file is missing, empty, or lacks required
    columns. Trusts CSV row order — callers write seq-sorted elsewhere.
    """
    csv_path = os.path.join(project_dir, 'reference', 'spine.csv')
    if not os.path.isfile(csv_path):
        return []
    try:
        with open(csv_path, encoding='utf-8') as f:
            raw = f.read().replace('\r\n', '\n').replace('\r', '')
    except (OSError, UnicodeDecodeError) as e:
        log(f'WARNING: could not read {csv_path}: {e}')
        return []
    lines = [l for l in raw.splitlines() if l.strip()]
    if len(lines) < 2:
        return []
    headers = lines[0].split('|')
    required = {'id', 'summary', 'function'}
    if not required.issubset(set(headers)):
        log(f'WARNING: spine.csv missing required columns; have {headers}, '
            f'need {sorted(required)}. Skipping spine mode.')
        return []
    out: list[SpineEvent] = []
    for i, line in enumerate(lines[1:], start=1):
        cells = line.split('|')
        if len(cells) != len(headers):
            log(f'WARNING: skipping malformed spine row {i} in {csv_path} '
                f'({len(cells)} cells, expected {len(headers)})')
            continue
        row = dict(zip(headers, cells))
        event_id = row.get('id', '').strip()
        summary = row.get('summary', '').strip()
        if not event_id or not summary:
            # A row that parsed structurally but lacks required identity
            # is almost always an in-progress edit or migration drift —
            # silently dropping it lets the LLM score a spine that's
            # missing an event without telling anyone.
            missing = []
            if not event_id:
                missing.append('id')
            if not summary:
                missing.append('summary')
            log(f'WARNING: spine.csv row {i} missing required field(s) '
                f'{", ".join(missing)}; skipping. '
                f'(id={event_id or "<blank>"})')
            continue
        out.append(SpineEvent(
            id=event_id,
            title=row.get('title', '').strip(),
            summary=summary,
            function=row.get('function', '').strip(),
        ))
    return out


def parse_architecture(project_dir: str) -> list[SceneRow]:
    """Read reference/architecture.csv as an ordered list of SceneRow.

    Required columns: id, summary, spine_event. Other architecture
    fields (action_sequel, emotional_arc, value_at_stake, value_shift,
    turning_point, title) are read when present and default to empty
    strings otherwise. Returns [] when the file is missing or lacks
    required columns.
    """
    csv_path = os.path.join(project_dir, 'reference', 'architecture.csv')
    if not os.path.isfile(csv_path):
        return []
    try:
        with open(csv_path, encoding='utf-8') as f:
            raw = f.read().replace('\r\n', '\n').replace('\r', '')
    except (OSError, UnicodeDecodeError) as e:
        log(f'WARNING: could not read {csv_path}: {e}')
        return []
    lines = [l for l in raw.splitlines() if l.strip()]
    if len(lines) < 2:
        return []
    headers = lines[0].split('|')
    required = {'id', 'summary', 'spine_event'}
    if not required.issubset(set(headers)):
        log(f'WARNING: architecture.csv missing required columns; have '
            f'{headers}, need {sorted(required)}. Skipping architecture mode.')
        return []
    out: list[SceneRow] = []
    for i, line in enumerate(lines[1:], start=1):
        cells = line.split('|')
        if len(cells) != len(headers):
            log(f'WARNING: skipping malformed architecture row {i} in '
                f'{csv_path} ({len(cells)} cells, expected {len(headers)})')
            continue
        row = dict(zip(headers, cells))
        scene_id = row.get('id', '').strip()
        summary = row.get('summary', '').strip()
        if not scene_id or not summary:
            missing = []
            if not scene_id:
                missing.append('id')
            if not summary:
                missing.append('summary')
            log(f'WARNING: architecture.csv row {i} missing required '
                f'field(s) {", ".join(missing)}; skipping. '
                f'(id={scene_id or "<blank>"})')
            continue
        out.append(SceneRow(
            id=scene_id,
            title=row.get('title', '').strip(),
            summary=summary,
            spine_event=row.get('spine_event', '').strip(),
            action_sequel=row.get('action_sequel', '').strip(),
            emotional_arc=row.get('emotional_arc', '').strip(),
            value_at_stake=row.get('value_at_stake', '').strip(),
            value_shift=row.get('value_shift', '').strip(),
            turning_point=row.get('turning_point', '').strip(),
        ))
    return out


def read_project_register(project_dir: str) -> Register:
    """Return the project's declared register from storyforge.yaml's
    `project.register` field. Defaults to 'balanced' when absent or
    unrecognized. Logs INFO in either fallback case so the author can
    see when their score is being computed against the default target."""
    raw = read_yaml_field('project.register', project_dir) or ''
    register = raw.strip().lower()
    if not register:
        log('INFO: project.register not declared in storyforge.yaml; '
            'scoring architecture against the balanced 40-60% action '
            'band. Set project.register to thriller/literary/atmospheric/'
            'etc. for register-specific scoring.')
        return 'balanced'
    if register not in KNOWN_REGISTERS:
        log(f'INFO: project.register={raw!r} is not a recognized register '
            f'({", ".join(KNOWN_REGISTERS)}); the scoring prompt will fall '
            'back to a balanced target band.')
        return 'balanced'
    return register  # type: ignore[return-value]


def gather_pitch_artifacts(project_dir: str) -> PitchArtifacts:
    """Read the artifacts the story-power rubric operates on.

    Always returns the six-field PitchArtifacts — empty strings for any
    artifact that is absent. The caller (score_story_power) enforces
    the actual requirement: both logline and synopsis must be present
    and non-empty. Spine and architecture summaries are optional
    context (they improve specificity scoring when present).
    """
    summary = parse_story_summary(project_dir) or {}
    return PitchArtifacts(
        logline=summary.get('logline', '').strip(),
        synopsis=summary.get('synopsis', '').strip(),
        act_shape=summary.get('act_shape', '').strip(),
        theme=summary.get('theme', '').strip(),
        spine_summaries=_summary_column_from_csv(
            os.path.join(project_dir, 'reference', 'spine.csv'),
        ),
        architecture_summaries=_summary_column_from_csv(
            os.path.join(project_dir, 'reference', 'architecture.csv'),
        ),
    )


def _summary_column_from_csv(csv_path: str) -> str:
    """Pull the `summary` column from a pipe-delimited CSV as a numbered
    bullet list. Returns '' if the file is missing or has no summary col.

    Logs a WARNING per row whose cell count doesn't match the header
    so a schema drift between spine.csv / architecture.csv and this
    reader surfaces instead of silently dropping rows from the prompt.
    """
    if not os.path.isfile(csv_path):
        return ''
    try:
        with open(csv_path, encoding='utf-8') as f:
            raw = f.read().replace('\r\n', '\n').replace('\r', '')
    except (OSError, UnicodeDecodeError) as e:
        log(f'WARNING: could not read {csv_path}: {e}')
        return ''
    lines = [l for l in raw.splitlines() if l.strip()]
    if len(lines) < 2:
        return ''
    headers = lines[0].split('|')
    if 'summary' not in headers:
        return ''
    out: list[str] = []
    for i, line in enumerate(lines[1:], start=1):
        cells = line.split('|')
        if len(cells) != len(headers):
            log(f'WARNING: skipping malformed row {i} in {csv_path} '
                f'({len(cells)} cells, expected {len(headers)})')
            continue
        row = dict(zip(headers, cells))
        s = row.get('summary', '').strip()
        if s:
            out.append(f'{i}. {s}')
    return '\n'.join(out)


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

def _build_prompt(artifacts: PitchArtifacts, rubric: str) -> str:
    """Assemble the LLM prompt for full-mode scoring."""
    axes_block = '\n'.join(
        f'  - "{a.key}": "{a.name}"' for a in AXES
    )
    return f"""You are evaluating the story DESIGN of a project at the pitch tier,
using the rubric provided. Do NOT score prose quality — score whether
the story is structurally and thematically built to last.

# Rubric

{rubric}

# Pitch artifacts

## Logline
{artifacts.logline or '(empty)'}

## Synopsis
{artifacts.synopsis or '(empty)'}

## Act-shape
{artifacts.act_shape or '(empty)'}

## Theme
{artifacts.theme or '(empty)'}

## Spine (one sentence per event)
{artifacts.spine_summaries or '(empty)'}

## Architecture (one sentence per anchor)
{artifacts.architecture_summaries or '(empty)'}

# Task

Return a JSON object with this exact shape:

{{
  "axes": {{
{axes_block}
  }},
  "scores": [
    {{
      "axis": "{AXES[0].key}",
      "score": 1-10 integer,
      "positive_signals": "semicolon-separated quoted signals from the pitch",
      "negative_signals": "semicolon-separated quoted abstractions / gaps",
      "rationale": "one-sentence justification grounded in the pitch"
    }},
    ... one entry per axis key in the order listed above ...
  ],
  "diagnostic": {{
    "cross_axis_root_cause": "one sentence: when two or more axes share a single underlying gap, name it",
    "high_leverage_move": "one sentence: ONE revision the author could make that lifts multiple axes",
    "example_sentence": "an optional concrete sentence to insert in the synopsis that would deliver the move"
  }}
}}

Reserve scores of 10 for prose-verified excellence; cap synopsis-stage
scores at 9 on most axes. Be specific and grounded — quote the pitch.
Return ONLY the JSON object.
"""


# ---------------------------------------------------------------------------
# Public scoring entry points
# ---------------------------------------------------------------------------

def score_story_power(project_dir: str, coaching: CoachingLevel,
                      dry_run: bool = False) -> StoryPowerResult:
    """Run the story-power scorecard at the given coaching level.

    See StoryPowerResult for the return shape; status is the outcome
    (ok / partial / unparseable / llm_error / dry_run / no_*),
    coaching is the requested level, and mode is a human-readable
    display string composed from those two for log lines.
    """
    artifacts = gather_pitch_artifacts(project_dir)
    missing = [k for k in ('logline', 'synopsis')
               if not getattr(artifacts, k)]
    if missing:
        log('ERROR: story-power scoring requires reference/story-summary.md '
            f'with both a logline and a synopsis. Missing: {", ".join(missing)}.')
        return _empty_result(coaching, 'no_input')

    rubric = _load_rubric()
    if not rubric and coaching != 'strict':
        log('ERROR: story-power rubric not found at '
            'references/story-power-rubric.md. Without the rubric the LLM '
            'has nothing to anchor its scores. Restore the file or use '
            '--coaching strict for the deterministic checklist.')
        return _empty_result(coaching, 'no_rubric')
    # Microsecond-resolution timestamp + non-existence loop to keep two
    # back-to-back runs from clobbering each other.
    output_dir = _allocate_output_dir(project_dir)

    if coaching == 'strict':
        if dry_run:
            log(f'DRY RUN — would write strict checklist to {output_dir}')
            return _empty_result('strict', 'dry_run', output_dir=output_dir)
        os.makedirs(output_dir, exist_ok=True)
        spine_events = parse_spine(project_dir)
        architecture_scenes = parse_architecture(project_dir)
        _write_strict_checklist(output_dir, artifacts, rubric,
                                  spine_events, architecture_scenes)
        return _empty_result('strict', 'ok', output_dir=output_dir)

    if dry_run:
        log(f'DRY RUN — would call LLM to score 8 axes; output → {output_dir}')
        return _empty_result(coaching, 'dry_run', output_dir=output_dir)

    # full + coach both call the LLM; differ only in destination.
    if not os.environ.get('ANTHROPIC_API_KEY'):
        log('ERROR: ANTHROPIC_API_KEY is not set. story-power scoring in '
            f'{coaching} coaching requires an API key. Set it and re-run, '
            'or use --coaching strict for the deterministic checklist.')
        return _empty_result(coaching, 'no_api_key')

    os.makedirs(output_dir, exist_ok=True)
    log_dir = os.path.join(project_dir, 'working', 'logs', 'story-power')
    log_file = os.path.join(log_dir, os.path.basename(output_dir) + '.json')
    parsed, llm_status = _invoke_and_parse(project_dir, output_dir, log_file,
                                            artifacts, rubric, coaching)
    if not parsed:
        return _empty_result(coaching, llm_status, output_dir=output_dir)

    scores = _extract_scores(parsed)
    missing_axes = [a.key for a in AXES if a.key not in scores]
    if missing_axes:
        log(f'WARNING: story-power LLM omitted or returned non-numeric '
            f'scores for {len(missing_axes)} axis/axes: '
            f'{", ".join(missing_axes)}. Composite reflects the present '
            'axes only.')
    composite = composite_score(scores)
    deltas = _compute_deltas(project_dir, scores)

    if coaching == 'full':
        _write_full_scorecard(output_dir, scores, parsed, composite,
                               deltas, artifacts, recover_hint=log_file)
    else:
        _write_coach_brief(output_dir, scores, parsed, composite,
                           deltas, artifacts, recover_hint=log_file)

    status: StoryPowerStatus = 'partial' if missing_axes else 'ok'

    # Pitch-only is a valid result; the act-shape and spine extensions
    # are additive, not replacements. A failed extension never overwrites
    # the pitch scorecard.
    act_shape = parse_act_shape(artifacts.act_shape)
    act_shape_extension: ActShapeExtension | None = None
    if act_shape:
        log('Act-shape detected — running Layer 1 (per-act matrix) + '
            'Layer 2 (structural axes).')
        act_shape_extension = _run_act_shape_extension(
            project_dir, output_dir, log_dir, act_shape, artifacts,
            rubric, coaching,
        )
        # Any non-ok act-shape outcome degrades the overall status so a
        # consumer that branches on `result['status']` sees the failure
        # even if they don't drill into result['act_shape']['status'].
        if act_shape_extension['status'] != 'ok':
            status = 'partial'

    # Spine mode runs independently of act-shape — both can fire on the
    # same artifacts and the diagnostic outputs coexist in the same dir.
    spine_events = parse_spine(project_dir)
    spine_extension: SpineExtension | None = None
    if spine_events:
        log(f'Spine detected ({len(spine_events)} events) — running per-event '
            'matrix + whole-spine axes.')
        spine_extension = _run_spine_extension(
            project_dir, output_dir, log_dir, spine_events, artifacts,
            act_shape, rubric, coaching,
        )
        if spine_extension['status'] != 'ok':
            status = 'partial'

    architecture_scenes = parse_architecture(project_dir)
    architecture_extension: ArchitectureExtension | None = None
    if architecture_scenes:
        register = read_project_register(project_dir)
        log(f'Architecture detected ({len(architecture_scenes)} scenes, '
            f'register={register}) — running per-scene matrix + '
            'whole-architecture axes.')
        architecture_extension = _run_architecture_extension(
            project_dir, output_dir, log_dir, architecture_scenes,
            spine_events, artifacts, register, rubric, coaching,
        )
        if architecture_extension['status'] != 'ok':
            status = 'partial'

    return _result(
        coaching=coaching, status=status, output_dir=output_dir,
        composite=composite, scores=scores, deltas=deltas,
        diagnostic=parsed.get('diagnostic') or {},
        act_shape=act_shape_extension,
        spine=spine_extension,
        architecture=architecture_extension,
    )


def _compose_mode(coaching: CoachingLevel, status: StoryPowerStatus) -> str:
    """Human-readable display string for `result['mode']`."""
    if status == 'ok':
        return coaching
    return f'{coaching} ({status})'


def _result(*, coaching: CoachingLevel, status: StoryPowerStatus,
             output_dir: str, composite: float,
             scores: dict[str, int], deltas: dict[str, int],
             diagnostic: dict,
             act_shape: ActShapeExtension | None = None,
             spine: SpineExtension | None = None,
             architecture: ArchitectureExtension | None = None,
             ) -> StoryPowerResult:
    return {
        'coaching': coaching,
        'status': status,
        'mode': _compose_mode(coaching, status),
        'output_dir': output_dir,
        'composite': composite,
        'scores': scores,
        'deltas': deltas,
        'diagnostic': diagnostic,
        'act_shape': act_shape,
        'spine': spine,
        'architecture': architecture,
    }


def _empty_result(coaching: CoachingLevel, status: StoryPowerStatus, *,
                   output_dir: str = '') -> StoryPowerResult:
    """Helper for the empty-data result shape across early returns."""
    return _result(
        coaching=coaching, status=status, output_dir=output_dir,
        composite=0.0, scores={}, deltas={}, diagnostic={},
    )


def _allocate_output_dir(project_dir: str) -> str:
    """Microsecond-resolution timestamped directory under working/scores/story-power.

    Two runs in the same microsecond are vanishingly unlikely, but the
    non-existence loop still guards against it so a back-to-back invocation
    can never clobber the prior run's CSV.
    """
    base = os.path.join(project_dir, 'working', 'scores', 'story-power')
    for _ in range(8):
        ts = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S_%fZ')
        candidate = os.path.join(base, ts)
        if not os.path.exists(candidate):
            return candidate
    # Vanishingly unlikely fallback — keep returning a unique-enough path.
    ts = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S_%fZ')
    return os.path.join(base, ts + '_x')


def _load_rubric() -> str:
    """Return the rubric text from references/story-power-rubric.md.

    Returns '' when the file is missing or unreadable. The caller decides
    whether that's a fail-stop (full/coach) or an acceptable fallback
    (strict, which uses only the per-axis section headings).
    """
    path = os.path.join(get_plugin_dir(), 'references',
                        'story-power-rubric.md')
    try:
        with open(path, encoding='utf-8') as f:
            return f.read()
    except (OSError, UnicodeDecodeError) as e:
        log(f'WARNING: could not read references/story-power-rubric.md: {e}')
        return ''


def _invoke_and_parse(project_dir: str, output_dir: str, log_file: str,
                       artifacts: PitchArtifacts, rubric: str,
                       coaching: CoachingLevel,
                       ) -> tuple[dict | None, StoryPowerStatus]:
    """Call the LLM and return (parsed_json, status).

    status is 'ok' on success, 'llm_error' if the API call threw, and
    'unparseable' if it returned but the response did not parse. The
    caller may upgrade 'ok' to 'partial' if axis extraction is partial.
    """
    prompt = _build_prompt(artifacts, rubric)
    model = select_model('creative')
    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    try:
        invoke_to_file(prompt, model, log_file, max_tokens=4096)
    except Exception as e:
        log(f'ERROR: story-power LLM call failed: {e}')
        return None, 'llm_error'
    text = _read_response_text(log_file)
    parsed = _parse_response(text)
    if not parsed:
        _record_cost(project_dir, log_file, model, target='story-power:unparseable')
        log(f'ERROR: story-power LLM response unparseable; raw at {log_file}')
        return None, 'unparseable'
    _record_cost(project_dir, log_file, model)
    return parsed, 'ok'


def _read_response_text(log_file: str) -> str:
    try:
        with open(log_file, encoding='utf-8') as f:
            resp = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        log(f'WARNING: could not read story-power response file: {e}')
        return ''
    for block in resp.get('content', []):
        if block.get('type') == 'text':
            return block.get('text', '')
    return ''


def _extract_scores(parsed: dict) -> dict[str, int]:
    """Pull {axis_key: int_score} from the parsed LLM response.

    Tolerant: drops any row missing/unknown axis, drops any non-coercible
    score. The caller checks which axes are missing and warns. Bounded to
    1-10 since out-of-range numbers are nearly always parse artifacts.
    """
    out: dict[str, int] = {}
    for row in parsed.get('scores') or []:
        if not isinstance(row, dict):
            continue
        axis = row.get('axis')
        if axis not in AXIS_BY_KEY:
            continue
        raw = row.get('score')
        try:
            score = int(raw)
        except (TypeError, ValueError):
            continue
        if not 1 <= score <= 10:
            continue
        out[axis] = score
    return out


def _parse_response(text: str) -> dict | None:
    """Tolerant JSON parse: direct → fenced → greedy. Validates shape.

    Logs WARNING when JSON parsed but the shape was wrong (separable from
    "no valid JSON found at all"), so authors can tell whether to fix the
    prompt or just retry.
    """
    saw_shape_failure = False

    def _take(obj):
        nonlocal saw_shape_failure
        if not isinstance(obj, dict):
            return None
        scores = obj.get('scores')
        if not isinstance(scores, list):
            saw_shape_failure = True
            return None
        return obj
    try:
        out = _take(json.loads(text))
        if out is not None:
            return out
    except json.JSONDecodeError:
        pass
    m = re.search(r'```(?:json)?\s*\n(.*?)\n```', text, re.DOTALL)
    if m:
        try:
            out = _take(json.loads(m.group(1).strip()))
            if out is not None:
                return out
        except json.JSONDecodeError:
            pass
    m = re.search(r'\{.*\}', text, re.DOTALL)
    if m:
        try:
            out = _take(json.loads(m.group(0)))
            if out is not None:
                return out
        except json.JSONDecodeError:
            pass
    if saw_shape_failure:
        log('WARNING: story-power LLM returned valid JSON but with the wrong '
            'shape (missing "scores" list). Treating as unparseable.')
    return None


def _record_cost(project_dir: str, log_file: str, model: str, *,
                  target: str = 'story-power') -> None:
    try:
        with open(log_file, encoding='utf-8') as f:
            resp = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        log(f'WARNING: cost ledger update failed reading {log_file}: {e}')
        return
    usage = extract_usage(resp)
    in_tok = usage.get('input_tokens', 0)
    out_tok = usage.get('output_tokens', 0)
    if in_tok == 0 and out_tok == 0:
        # An LLM round-trip that records zero tokens is almost always a
        # mocked or empty response. Logging a $0 ledger row hides this.
        log(f'WARNING: story-power response had zero input+output tokens; '
            f'skipping cost ledger entry (response at {log_file}).')
        return
    cost = calculate_cost_from_usage(usage, model)
    log_operation(
        project_dir, 'score-story-power', model,
        in_tok, out_tok, cost,
        target=target,
        cache_read=usage.get('cache_read', 0),
        cache_create=usage.get('cache_create', 0),
    )


# ---------------------------------------------------------------------------
# Delta tracking
# ---------------------------------------------------------------------------

def _compute_deltas(project_dir: str,
                     current_scores: dict[str, int]) -> dict[str, int]:
    """Compare current scores against the most recent prior run.

    Returns {axis_key: delta} where delta = current - previous. Empty
    when no prior run exists. Skips the just-created current directory
    by filtering on scorecard.csv presence (the current dir hasn't
    written its scorecard yet at this point in the flow).
    """
    base = os.path.join(project_dir, 'working', 'scores', 'story-power')
    if not os.path.isdir(base):
        return {}
    # Restrict to directories that actually have a scorecard.csv on disk
    # — the just-created current run is still empty when this is called.
    prior_runs = sorted(d for d in os.listdir(base)
                        if os.path.isdir(os.path.join(base, d))
                        and os.path.isfile(
                            os.path.join(base, d, 'scorecard.csv'),
                        ))
    if not prior_runs:
        return {}
    prev_path = os.path.join(base, prior_runs[-1], 'scorecard.csv')
    prev_scores = _read_scorecard_scores(prev_path)
    # Surface schema drift — if the previous CSV's axis set differs from
    # the current run's, deltas are at best partial and at worst
    # comparing apples-to-not-quite-apples (axes added/removed across
    # runs).
    prev_axes = set(prev_scores)
    curr_axes = set(current_scores)
    if prev_axes and prev_axes != curr_axes:
        missing_prev = curr_axes - prev_axes
        missing_curr = prev_axes - curr_axes
        details = []
        if missing_prev:
            details.append(f'new in this run: {sorted(missing_prev)}')
        if missing_curr:
            details.append(f'absent in this run: {sorted(missing_curr)}')
        log('WARNING: story-power axis set drifted between runs ('
            + '; '.join(details) + '). Deltas cover only the overlap.')
    return {k: current_scores[k] - prev_scores[k]
            for k in current_scores if k in prev_scores}


def _read_scorecard_scores(path: str) -> dict[str, int]:
    """Read {axis: score} from a scorecard.csv."""
    if not os.path.isfile(path):
        return {}
    out: dict[str, int] = {}
    with open(path, encoding='utf-8') as f:
        lines = [l for l in f.read().splitlines() if l.strip()]
    if len(lines) < 2:
        return {}
    headers = lines[0].split('|')
    for line in lines[1:]:
        cells = line.split('|')
        if len(cells) != len(headers):
            continue
        row = dict(zip(headers, cells))
        axis = row.get('axis', '').strip()
        try:
            out[axis] = int(row.get('score', '0'))
        except ValueError:
            continue
    return out


# ---------------------------------------------------------------------------
# Act-shape extension (Layer 1 per-act matrix + Layer 2 structural axes)
# ---------------------------------------------------------------------------

ACT_KEYS: tuple[str, ...] = ('act1', 'act2', 'act3')


def _build_act_shape_prompt(act_shape: ActShape, artifacts: PitchArtifacts,
                             rubric: str) -> str:
    """Assemble the prompt that asks for per-act matrix + structural axes.

    Returns a JSON response with two top-level objects: `per_act` (the
    Layer 1 3×8 matrix) and `structural` (the Layer 2 4-axis scores)
    plus a cross-act diagnostic.
    """
    pitch_axis_list = ', '.join(f'"{a.key}"' for a in AXES)
    structural_axis_list = ', '.join(f'"{a.key}"' for a in STRUCTURAL_AXES)
    return f"""You are scoring the ACT-SHAPE of a project at the structural-spec
tier, using the rubric provided. The eight pitch-level axes have
already been scored against the synopsis as a whole; your job now is
to re-apply those eight axes per act AND to score the four cross-act
structural axes defined in the "Layer 2" section of the rubric.

# Rubric

{rubric}

# Pitch context (already scored — do not re-score the synopsis)

## Logline
{artifacts.logline}

## Synopsis
{artifacts.synopsis}

## Theme
{artifacts.theme or '(empty)'}

# Act-shape under evaluation

## Act 1
{act_shape.act1}

## Act 2
{act_shape.act2}

## Act 3
{act_shape.act3}

# Optional structural context

## Spine (one sentence per event)
{artifacts.spine_summaries or '(empty)'}

## Architecture (one sentence per anchor)
{artifacts.architecture_summaries or '(empty)'}

# Task

Valid pitch axis keys (use exactly these in the `per_act` scores):
{pitch_axis_list}

Valid structural axis keys (use exactly these in `structural`):
{structural_axis_list}

Return a JSON object with this exact shape:

{{
  "per_act": [
    {{
      "act": "act1",
      "scores": [
        {{"axis": "{AXES[0].key}", "score": 1-10 integer,
          "rationale": "one-sentence justification grounded in this act"}},
        ... one entry per pitch axis key ...
      ]
    }},
    ... one entry per act in order: act1, act2, act3 ...
  ],
  "structural": [
    {{"axis": "{STRUCTURAL_AXES[0].key}",
      "score": 1-10 integer,
      "positive_signals": "semicolon-separated quoted signals across acts",
      "negative_signals": "semicolon-separated quoted gaps across acts",
      "rationale": "one-sentence justification grounded in cross-act relationships"}},
    ... one entry per structural axis key ...
  ],
  "structural_diagnostic": {{
    "cross_act_pattern": "one sentence: when an axis drops in one act vs the others, or when two structural axes co-locate a problem, name it",
    "high_leverage_move": "one sentence: ONE structural change that would lift multiple axes across layers",
    "example_beat": "an optional concrete beat to insert or revise that would deliver the move"
  }}
}}

Score per-act using the same 1-10 bands as the pitch rubric; an act
that scores 9 in isolation is one whose execution at the structural-
spec level is top-tier. The four structural axes are scored over
relationships between acts — do not double-count Layer 1 drops as
Layer 2 problems; the rubric explicitly keeps them independent so the
diagnostic can name causes vs. symptoms.

Reserve 10 for prose-verified excellence. Be specific and grounded —
quote the act-shape. Return ONLY the JSON object.
"""


def _extract_per_act_scores(parsed: dict) -> dict[str, dict[str, int]]:
    """Pull {act_key: {pitch_axis_key: score}} from the act-shape response.

    Tolerant in the same way _extract_scores is: drops malformed rows
    rather than raising. Returns only act/axis combinations that survive
    the (axis-known, score-int, score-in-range) checks.
    """
    out: dict[str, dict[str, int]] = {a: {} for a in ACT_KEYS}
    for act_row in parsed.get('per_act') or []:
        if not isinstance(act_row, dict):
            continue
        act_key = act_row.get('act')
        if act_key not in ACT_KEYS:
            continue
        for score_row in act_row.get('scores') or []:
            if not isinstance(score_row, dict):
                continue
            axis = score_row.get('axis')
            if axis not in AXIS_BY_KEY:
                continue
            try:
                score = int(score_row.get('score'))
            except (TypeError, ValueError):
                continue
            if not 1 <= score <= 10:
                continue
            out[act_key][axis] = score
    return out


def _extract_structural_scores(parsed: dict) -> dict[str, int]:
    """Pull {structural_axis_key: score} from the act-shape response."""
    out: dict[str, int] = {}
    for row in parsed.get('structural') or []:
        if not isinstance(row, dict):
            continue
        axis = row.get('axis')
        if axis not in STRUCTURAL_AXIS_BY_KEY:
            continue
        try:
            score = int(row.get('score'))
        except (TypeError, ValueError):
            continue
        if not 1 <= score <= 10:
            continue
        out[axis] = score
    return out


def _empty_extension(status: StoryPowerStatus) -> ActShapeExtension:
    """Build a placeholder ActShapeExtension for a failed run.

    The extension lives in the result so consumers can distinguish
    "act-shape attempted and failed" (act_shape is not None,
    status in {'llm_error', 'unparseable'}) from "act-shape never
    attempted" (act_shape is None).
    """
    return {
        'status': status,
        'per_act_scores': {},
        'structural_axis_scores': {},
        'structural_diagnostic': {},
    }


def _run_act_shape_extension(project_dir: str, output_dir: str,
                               log_dir: str, act_shape: ActShape,
                               artifacts: PitchArtifacts, rubric: str,
                               coaching: CoachingLevel,
                               ) -> ActShapeExtension:
    """Run the Layer 1 + Layer 2 LLM call and write the act-shape CSVs.

    Always returns an ActShapeExtension; status carries the outcome:
    'ok' / 'partial' on success, 'llm_error' / 'unparseable' on failure.
    Pitch result still stands either way — act-shape never throws past
    this boundary.
    """
    prompt = _build_act_shape_prompt(act_shape, artifacts, rubric)
    model = select_model('creative')
    log_file = os.path.join(log_dir,
                            os.path.basename(output_dir) + '-act-shape.json')
    os.makedirs(log_dir, exist_ok=True)
    try:
        invoke_to_file(prompt, model, log_file, max_tokens=8192)
    except Exception as e:
        log(f'ERROR: act-shape LLM call failed: {e}. Pitch-mode scorecard '
            'still stands.')
        return _empty_extension('llm_error')
    text = _read_response_text(log_file)
    parsed = _parse_response_act_shape(text)
    if not parsed:
        _record_cost(project_dir, log_file, model,
                     target='story-power:act-shape:unparseable')
        log(f'ERROR: act-shape LLM response unparseable; raw at {log_file}. '
            'Pitch-mode scorecard still stands.')
        return _empty_extension('unparseable')
    _record_cost(project_dir, log_file, model, target='story-power:act-shape')

    per_act = _extract_per_act_scores(parsed)
    structural = _extract_structural_scores(parsed)
    structural_diag = parsed.get('structural_diagnostic') or {}

    # Floor on partial extraction: if a whole act is empty or structural
    # came back empty, refuse to write the matching CSV. Empty cells in
    # a published CSV are read as data ("zero across the board"); silent
    # half-empty tables would mislead more than the missing file does.
    empty_acts = [a for a in ACT_KEYS if not per_act.get(a)]
    has_any_per_act = any(per_act.get(a) for a in ACT_KEYS)
    if empty_acts and has_any_per_act:
        log(f'ERROR: act-shape extraction produced zero valid scores for '
            f'{", ".join(empty_acts)}; refusing to write per-act-matrix.csv '
            f'with empty column(s). Raw response: {log_file}')
    if not structural:
        log(f'ERROR: act-shape extraction produced zero valid structural '
            f'axes; refusing to write structural-axes.csv. Raw response: '
            f'{log_file}')

    missing_per_act = sum(len(AXIS_KEYS) - len(scores)
                          for scores in per_act.values())
    missing_struct = [a.key for a in STRUCTURAL_AXES if a.key not in structural]
    status: StoryPowerStatus = 'ok'
    if missing_per_act or missing_struct:
        status = 'partial'
        parts = []
        if missing_per_act:
            parts.append(f'{missing_per_act} per-act cell(s) missing')
        if missing_struct:
            parts.append(
                f'{len(missing_struct)} structural axis/axes missing '
                f'({", ".join(missing_struct)})'
            )
        log(f'WARNING: act-shape extraction partial — {"; ".join(parts)}.')
    # Couples the type-system invariant: ok ⇒ non-empty payload. The
    # missing-count arithmetic above enforces this in practice; the
    # assert catches a future shortcut that bypasses it.
    if status == 'ok':
        assert per_act and structural, (
            'act-shape extension status=ok requires non-empty per_act '
            'and structural scores'
        )

    # Only write outputs that have data backing them. Missing files
    # are clearer signal than empty rows.
    write_matrix = has_any_per_act and not empty_acts
    write_structural = bool(structural)
    if coaching == 'full':
        if write_matrix:
            _write_per_act_matrix(output_dir, per_act, parsed,
                                  recover_hint=log_file)
        if write_structural:
            _write_structural_axes(output_dir, structural, parsed,
                                   recover_hint=log_file)
        if write_matrix or write_structural:
            _append_structural_diagnostic(output_dir, per_act,
                                           structural, structural_diag)
    else:
        if write_matrix or write_structural:
            _append_act_shape_coaching_brief(
                output_dir, per_act, structural, parsed, structural_diag,
                recover_hint=log_file,
            )

    return {
        'status': status,
        'per_act_scores': per_act,
        'structural_axis_scores': structural,
        'structural_diagnostic': structural_diag,
    }


def _parse_response_act_shape(text: str) -> dict | None:
    """Tolerant JSON parse for the act-shape payload.

    Same three-tier fallback as _parse_response (raw → fenced → greedy),
    but the shape check looks for `per_act` AND `structural` rather than
    `scores`. When shape failure is the reason for None, logs a WARNING
    naming which list(s) were missing — this is more actionable than the
    caller's generic "unparseable" ERROR for prompt debugging.
    """
    missing_fields: list[str] = []

    def _take(obj):
        if not isinstance(obj, dict):
            return None
        per_act = obj.get('per_act')
        structural = obj.get('structural')
        local_missing = []
        if not isinstance(per_act, list):
            local_missing.append('per_act')
        if not isinstance(structural, list):
            local_missing.append('structural')
        if local_missing:
            missing_fields[:] = local_missing
            return None
        return obj
    try:
        out = _take(json.loads(text))
        if out is not None:
            return out
    except json.JSONDecodeError:
        pass
    m = re.search(r'```(?:json)?\s*\n(.*?)\n```', text, re.DOTALL)
    if m:
        try:
            out = _take(json.loads(m.group(1).strip()))
            if out is not None:
                return out
        except json.JSONDecodeError:
            pass
    m = re.search(r'\{.*\}', text, re.DOTALL)
    if m:
        try:
            out = _take(json.loads(m.group(0)))
            if out is not None:
                return out
        except json.JSONDecodeError:
            pass
    if missing_fields:
        log(f'WARNING: act-shape LLM returned valid JSON but missing '
            f'required list(s): {", ".join(missing_fields)}.')
    return None


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------

def _sanitize_cell(value: str) -> str:
    if not isinstance(value, str):
        value = str(value)
    return value.replace('|', '/').replace('\n', ' ').replace('\r', '').strip()


def _safe_write(path: str, content: str, *, recover_hint: str = '') -> bool:
    """Write content to path, surfacing OSError without crashing the run.

    The LLM call already cost money; a downstream filesystem failure
    (disk full, permission denied) shouldn't lose the result silently.
    Returns True on success. recover_hint names the log file the author
    can recover from.
    """
    try:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
        return True
    except OSError as e:
        hint = f' Raw response: {recover_hint}' if recover_hint else ''
        log(f'ERROR: failed to write story-power output to {path}: {e}.{hint}')
        return False


def _write_full_scorecard(output_dir: str, scores: dict[str, int],
                            parsed: dict, composite: float,
                            deltas: dict[str, int],
                            artifacts: PitchArtifacts, *,
                            recover_hint: str = '') -> None:
    """full coaching: write scorecard.csv + diagnostic.md."""
    csv_path = os.path.join(output_dir, 'scorecard.csv')
    headers = ['axis', 'name', 'score', 'weight', 'positive_signals',
               'negative_signals', 'rationale']
    rows_by_axis = {r.get('axis'): r for r in parsed.get('scores', [])}
    lines = ['|'.join(headers)]
    for axis in AXES:
        row = rows_by_axis.get(axis.key, {})
        lines.append('|'.join(_sanitize_cell(c) for c in (
            axis.key,
            axis.name,
            str(row.get('score', '')),
            str(axis.weight),
            row.get('positive_signals', ''),
            row.get('negative_signals', ''),
            row.get('rationale', ''),
        )))
    _safe_write(csv_path, '\n'.join(lines) + '\n', recover_hint=recover_hint)

    md_path = os.path.join(output_dir, 'diagnostic.md')
    diag = parsed.get('diagnostic') or {}
    md_lines = [
        f'# Story-power scorecard — diagnostic',
        '',
        f'Composite (weighted): **{composite}** / 10.',
        '',
        '## Per-axis scores',
        '',
        '| Axis | Score | Weight | Δ vs last run |',
        '|---|---|---|---|',
    ]
    for axis in AXES:
        s = scores.get(axis.key, '–')
        d = deltas.get(axis.key)
        d_text = f'{d:+d}' if d is not None and d != 0 else ('–' if d is None else '0')
        md_lines.append(f'| {axis.name} | {s} | {axis.weight} | {d_text} |')
    md_lines.extend([
        '',
        '## Diagnostic',
        '',
        f'**Cross-axis root cause:** {diag.get("cross_axis_root_cause") or "(none identified)"}',
        '',
        f'**High-leverage move:** {diag.get("high_leverage_move") or "(none proposed)"}',
        '',
    ])
    example = diag.get('example_sentence')
    if example:
        md_lines.extend([
            '**Example sentence to consider:**',
            '',
            f'> {example}',
            '',
        ])
    _safe_write(md_path, '\n'.join(md_lines) + '\n', recover_hint=recover_hint)


def _write_coach_brief(output_dir: str, scores: dict[str, int],
                        parsed: dict, composite: float,
                        deltas: dict[str, int],
                        artifacts: PitchArtifacts, *,
                        recover_hint: str = '') -> None:
    """coach coaching: write a review brief with the LLM proposals +
    author-facing questions per axis."""
    md_path = os.path.join(output_dir, 'coaching-brief.md')
    diag = parsed.get('diagnostic') or {}
    rows_by_axis = {r.get('axis'): r for r in parsed.get('scores', [])}
    out: list[str] = [
        f'# Story-power scorecard — coaching brief',
        '',
        f'Proposed composite (weighted): {composite} / 10. The scores '
        'below are LLM proposals for author review — not authoritative. '
        'Use them to focus revision; the author decides what to act on.',
        '',
    ]
    for axis in AXES:
        row = rows_by_axis.get(axis.key, {})
        out.extend([
            f'## {axis.name} (proposed {row.get("score", "–")}, weight {axis.weight})',
            '',
            f'- Positive: {row.get("positive_signals", "—")}',
            f'- Negative: {row.get("negative_signals", "—")}',
            f'- Rationale: {row.get("rationale", "—")}',
            f'- Question: does the score match your read? If not, what '
            'signal is the LLM missing?',
            '',
        ])
    out.extend([
        '## Diagnostic',
        '',
        f'**Cross-axis root cause:** {diag.get("cross_axis_root_cause") or "(none identified)"}',
        '',
        f'**High-leverage move:** {diag.get("high_leverage_move") or "(none proposed)"}',
        '',
    ])
    example = diag.get('example_sentence')
    if example:
        out.extend([
            '**Example sentence to consider:**',
            '',
            f'> {example}',
            '',
        ])
    _safe_write(md_path, '\n'.join(out) + '\n', recover_hint=recover_hint)


def _write_strict_checklist(output_dir: str, artifacts: PitchArtifacts,
                              rubric: str,
                              spine_events: list[SpineEvent] | None = None,
                              architecture_scenes: list[SceneRow] | None = None,
                              ) -> None:
    """strict coaching: rule-based checklist of signals per axis, no LLM
    call. Extends with per-act + structural blanks when act-shape is
    populated, per-event + whole-spine blanks when spine.csv exists,
    and per-scene + whole-architecture blanks when architecture.csv
    exists — strict-mode authors get the same coverage the LLM modes
    produce automatically.
    """
    md_path = os.path.join(output_dir, 'self-scoring-checklist.md')
    out: list[str] = [
        '# Story-power scorecard — self-scoring checklist',
        '',
        f'Generated for coaching=strict on '
        f'{datetime.now(timezone.utc).isoformat()}. For each axis below, '
        'review the signals in the rubric and assign a 1-10 score yourself. '
        'No LLM call has been made. See references/story-power-rubric.md '
        'for full signal definitions and scoring bands.',
        '',
        '# Pitch tier (whole synopsis)',
        '',
    ]
    for axis in AXES:
        out.extend([
            f'## {axis.name} (weight {axis.weight})',
            '',
            f'Self-score (1-10): __',
            '',
            'Positive signals you found:',
            '- ',
            '',
            'Negative signals you found:',
            '- ',
            '',
        ])
    act_shape = parse_act_shape(artifacts.act_shape)
    if act_shape:
        out.extend([
            '# Act-shape tier (per act + structural)',
            '',
            'The eight pitch axes above, scored independently per act:',
            '',
        ])
        for act_label in ('Act 1', 'Act 2', 'Act 3'):
            out.extend([f'## {act_label}', ''])
            for axis in AXES:
                out.append(f'- {axis.name}: __')
            out.append('')
        out.extend([
            '# Cross-act structural axes',
            '',
            'These four axes measure relationships between acts (see the '
            '"Layer 2" section of the rubric for full signals).',
            '',
        ])
        for axis in STRUCTURAL_AXES:
            out.extend([
                f'## {axis.name} (weight {axis.weight})',
                '',
                f'Self-score (1-10): __',
                '',
                'Cross-act signals you found:',
                '- ',
                '',
            ])
    if spine_events:
        out.extend([
            '# Spine tier (per event + whole-spine)',
            '',
            'Three axes per spine event. The final event has no causal '
            'handoff — leave that blank for the last row.',
            '',
        ])
        for ev in spine_events:
            out.extend([
                f'## {ev.id} — {ev.function or "(no function)"}',
                '',
            ])
            for axis in PER_EVENT_AXES:
                out.append(f'- {axis.name}: __')
            out.append('')
        out.extend([
            '# Whole-spine axes',
            '',
            'Five axes scored over the spine as a whole (see the "Spine '
            'mode" section of the rubric for full signals).',
            '',
        ])
        for axis in SPINE_AXES:
            out.extend([
                f'## {axis.name} (weight {axis.weight})',
                '',
                f'Self-score (1-10): __',
                '',
                'Whole-spine signals you found:',
                '- ',
                '',
            ])
    if architecture_scenes:
        out.extend([
            '# Architecture tier (per scene + whole-architecture)',
            '',
            'Two axes per architecture scene (spine-event service, field coherence).',
            '',
        ])
        for s in architecture_scenes:
            out.extend([
                f'## {s.id} — serves {s.spine_event or "(no spine event)"}',
                '',
            ])
            for axis in PER_SCENE_AXES:
                out.append(f'- {axis.name}: __')
            out.append('')
        out.extend([
            '# Whole-architecture axes',
            '',
            'Five axes scored over the architecture as a whole (see the '
            '"Architecture mode" section of the rubric for full signals).',
            '',
        ])
        for axis in ARCHITECTURE_AXES:
            out.extend([
                f'## {axis.name} (weight {axis.weight})',
                '',
                f'Self-score (1-10): __',
                '',
                'Whole-architecture signals you found:',
                '- ',
                '',
            ])
    _safe_write(md_path, '\n'.join(out) + '\n')


# ---------------------------------------------------------------------------
# Act-shape writers (Layer 1 + Layer 2 outputs)
# ---------------------------------------------------------------------------

def _write_per_act_matrix(output_dir: str,
                            per_act: dict[str, dict[str, int]],
                            parsed: dict, *,
                            recover_hint: str = '') -> None:
    """Write `per-act-matrix.csv` — 3 acts × 8 pitch axes."""
    csv_path = os.path.join(output_dir, 'per-act-matrix.csv')
    headers = ['axis', 'name'] + list(ACT_KEYS)
    lines = ['|'.join(headers)]
    for axis in AXES:
        row = [axis.key, axis.name]
        for act in ACT_KEYS:
            row.append(str(per_act.get(act, {}).get(axis.key, '')))
        lines.append('|'.join(_sanitize_cell(c) for c in row))
    _safe_write(csv_path, '\n'.join(lines) + '\n', recover_hint=recover_hint)


def _write_structural_axes(output_dir: str,
                             structural: dict[str, int],
                             parsed: dict, *,
                             recover_hint: str = '') -> None:
    """Write `structural-axes.csv` — 4 cross-act structural scores."""
    csv_path = os.path.join(output_dir, 'structural-axes.csv')
    headers = ['axis', 'name', 'score', 'weight', 'positive_signals',
               'negative_signals', 'rationale']
    rows_by_axis = {r.get('axis'): r for r in parsed.get('structural', [])
                    if isinstance(r, dict)}
    lines = ['|'.join(headers)]
    for axis in STRUCTURAL_AXES:
        row = rows_by_axis.get(axis.key, {})
        lines.append('|'.join(_sanitize_cell(c) for c in (
            axis.key,
            axis.name,
            str(structural.get(axis.key, '')),
            str(axis.weight),
            row.get('positive_signals', ''),
            row.get('negative_signals', ''),
            row.get('rationale', ''),
        )))
    _safe_write(csv_path, '\n'.join(lines) + '\n', recover_hint=recover_hint)


def _append_structural_diagnostic(output_dir: str,
                                    per_act: dict[str, dict[str, int]],
                                    structural: dict[str, int],
                                    structural_diag: dict) -> None:
    """Append the cross-act section to the existing diagnostic.md."""
    md_path = os.path.join(output_dir, 'diagnostic.md')
    if not os.path.isfile(md_path):
        # The pitch-mode writer should have created this moments ago.
        # If it isn't here, an upstream _safe_write failed silently —
        # surface the cascade so the author knows two casualties came
        # from one root cause.
        log(f'WARNING: cross-act diagnostic could not be appended — '
            f'{md_path} does not exist (upstream pitch-diagnostic write '
            'likely failed). Per-act + structural scores were computed '
            'but their diagnostic narrative is lost.')
        return
    try:
        with open(md_path, encoding='utf-8') as f:
            existing = f.read()
    except OSError as e:
        log(f'WARNING: could not append cross-act diagnostic to {md_path}: {e}')
        return

    md_lines = [
        '## Per-act matrix (Layer 1)',
        '',
        '| Axis | Act 1 | Act 2 | Act 3 |',
        '|---|---|---|---|',
    ]
    for axis in AXES:
        cells = [str(per_act.get(act, {}).get(axis.key, '–'))
                 for act in ACT_KEYS]
        md_lines.append(f'| {axis.name} | {cells[0]} | {cells[1]} | {cells[2]} |')
    md_lines.extend([
        '',
        '## Cross-act structural axes (Layer 2)',
        '',
        '| Axis | Score | Weight |',
        '|---|---|---|',
    ])
    for axis in STRUCTURAL_AXES:
        s = structural.get(axis.key, '–')
        md_lines.append(f'| {axis.name} | {s} | {axis.weight} |')

    drops, skipped = _flag_act_drops(per_act)
    if drops:
        md_lines.extend(['', '### Per-axis drops', ''])
        for axis_key, act_key, gap in drops:
            axis = AXIS_BY_KEY[axis_key]
            md_lines.append(
                f'- **{axis.name}** drops in {act_key.upper()} '
                f'(gap of {gap} vs. the other two acts).'
            )
    if skipped:
        md_lines.extend([
            '',
            '### Axes skipped from drops analysis',
            '',
            'One or more acts had no score for these axes; cross-act '
            'drops could not be computed:',
            '',
        ])
        for axis_key in skipped:
            md_lines.append(f'- {AXIS_BY_KEY[axis_key].name}')

    md_lines.extend([
        '',
        '## Cross-act diagnostic',
        '',
        f'**Cross-act pattern:** {structural_diag.get("cross_act_pattern") or "(none identified)"}',
        '',
        f'**High-leverage move (structural):** {structural_diag.get("high_leverage_move") or "(none proposed)"}',
        '',
    ])
    example = structural_diag.get('example_beat')
    if example:
        md_lines.extend([
            '**Example beat to consider:**',
            '',
            f'> {example}',
            '',
        ])

    _safe_write(md_path, existing + '\n' + '\n'.join(md_lines) + '\n')


def _flag_act_drops(per_act: dict[str, dict[str, int]],
                     min_gap: int = 2,
                     ) -> tuple[list[tuple[str, str, int]], list[str]]:
    """Identify per-axis drops where one act lags ≥ min_gap behind the
    average of the other two.

    Returns (drops, skipped_axes). drops is a list of (axis_key,
    act_key, gap) tuples ordered by axis appearance in AXES, then by
    act order within each axis. skipped_axes lists axis keys where one
    or more acts had no score — surfacing these in the diagnostic keeps
    the author from reading a clean drops list as "no problems found"
    when really the analysis was incomplete.
    """
    out: list[tuple[str, str, int]] = []
    skipped: list[str] = []
    for axis in AXES:
        scores_by_act = {act: per_act.get(act, {}).get(axis.key)
                         for act in ACT_KEYS}
        if any(v is None for v in scores_by_act.values()):
            skipped.append(axis.key)
            continue
        for act in ACT_KEYS:
            other_avg = sum(scores_by_act[a] for a in ACT_KEYS
                            if a != act) / 2
            gap = round(other_avg - scores_by_act[act])
            if gap >= min_gap:
                out.append((axis.key, act, gap))
    return out, skipped


def _append_act_shape_coaching_brief(output_dir: str,
                                       per_act: dict[str, dict[str, int]],
                                       structural: dict[str, int],
                                       parsed: dict,
                                       structural_diag: dict, *,
                                       recover_hint: str = '') -> None:
    """coach coaching: append per-act + structural sections to the
    existing coaching-brief.md."""
    md_path = os.path.join(output_dir, 'coaching-brief.md')
    if not os.path.isfile(md_path):
        log(f'WARNING: act-shape coaching brief could not be appended — '
            f'{md_path} does not exist (upstream coach-brief write likely '
            'failed). Per-act + structural proposals were computed but '
            'are not captured in the brief.')
        return
    try:
        with open(md_path, encoding='utf-8') as f:
            existing = f.read()
    except OSError as e:
        log(f'WARNING: could not append act-shape coaching brief to {md_path}: {e}')
        return

    out: list[str] = [
        '# Act-shape extension (LLM proposals — author confirms)',
        '',
        'Per-act matrix and structural axes follow. The matrix surfaces '
        '*where* a problem lands; the structural axes name *why* it lands. '
        'Keeping them independent on purpose — use the structural scores '
        'to localize root cause, not as a justification to drag matrix '
        'scores up or down.',
        '',
        '## Per-act matrix (proposed)',
        '',
        '| Axis | Act 1 | Act 2 | Act 3 |',
        '|---|---|---|---|',
    ]
    for axis in AXES:
        cells = [str(per_act.get(act, {}).get(axis.key, '–'))
                 for act in ACT_KEYS]
        out.append(f'| {axis.name} | {cells[0]} | {cells[1]} | {cells[2]} |')

    out.extend(['', '## Cross-act structural axes (proposed)', ''])
    rows_by_axis = {r.get('axis'): r for r in parsed.get('structural', [])
                    if isinstance(r, dict)}
    for axis in STRUCTURAL_AXES:
        row = rows_by_axis.get(axis.key, {})
        s = structural.get(axis.key, '–')
        out.extend([
            f'### {axis.name} (proposed {s}, weight {axis.weight})',
            '',
            f'- Positive: {row.get("positive_signals", "—")}',
            f'- Negative: {row.get("negative_signals", "—")}',
            f'- Rationale: {row.get("rationale", "—")}',
            f'- Question: does this structural read match your sense of how '
            'the acts relate?',
            '',
        ])

    drops, skipped = _flag_act_drops(per_act)
    if drops:
        out.extend(['## Per-axis drops worth discussing', ''])
        for axis_key, act_key, gap in drops:
            axis = AXIS_BY_KEY[axis_key]
            out.append(
                f'- **{axis.name}** drops in {act_key.upper()} '
                f'(gap of {gap}). Is this an intentional shape choice or '
                'an unintentional dip?'
            )
        out.append('')
    if skipped:
        out.extend([
            '## Axes skipped from drops analysis',
            '',
            'One or more acts had no score for these axes; cross-act '
            'drops could not be computed:',
            '',
        ])
        for axis_key in skipped:
            out.append(f'- {AXIS_BY_KEY[axis_key].name}')
        out.append('')

    out.extend([
        '## Cross-act diagnostic',
        '',
        f'**Cross-act pattern:** {structural_diag.get("cross_act_pattern") or "(none identified)"}',
        '',
        f'**Proposed high-leverage move:** {structural_diag.get("high_leverage_move") or "(none proposed)"}',
        '',
    ])
    example = structural_diag.get('example_beat')
    if example:
        out.extend([
            '**Example beat to consider:**',
            '',
            f'> {example}',
            '',
        ])

    _safe_write(md_path, existing + '\n' + '\n'.join(out) + '\n',
                recover_hint=recover_hint)


# ---------------------------------------------------------------------------
# Spine extension (Layer 1 per-event + Layer 2 whole-spine)
# ---------------------------------------------------------------------------

WEAK_HANDOFF_THRESHOLD = 8  # see rubric §"Weak-handoff threshold"


def _empty_spine_extension(status: StoryPowerStatus) -> SpineExtension:
    """Placeholder SpineExtension for a failed spine run (mirrors _empty_extension)."""
    return {
        'status': status,
        'per_event_scores': {},
        'whole_spine_scores': {},
        'spine_diagnostic': {},
        'weak_handoffs': [],
        'proposed_fix': {},
    }


def _build_spine_prompt(events: list[SpineEvent], artifacts: PitchArtifacts,
                          act_shape: ActShape | None, rubric: str) -> str:
    """Assemble the spine-mode LLM prompt: per-event 3-axis matrix +
    5 whole-spine axes + diagnostic with proposed-fix clause."""
    per_event_axis_list = ', '.join(f'"{a.key}"' for a in PER_EVENT_AXES)
    spine_axis_list = ', '.join(f'"{a.key}"' for a in SPINE_AXES)
    events_block = '\n'.join(
        f'### {ev.id} ({ev.function or "no function"}) — '
        f'concreteness floor {function_concreteness_floor(ev.function)}\n'
        f'Title: {ev.title or "(none)"}\n'
        f'Summary: {ev.summary}'
        for ev in events
    )
    if act_shape:
        act_shape_block = (
            f'## Act 1\n{act_shape.act1}\n\n'
            f'## Act 2\n{act_shape.act2}\n\n'
            f'## Act 3\n{act_shape.act3}\n'
        )
    else:
        act_shape_block = (
            '(no act-shape populated — score `spine_act_shape_alignment` '
            'as 0 and mark it N/A in the rationale)'
        )
    final_event_id = events[-1].id if events else ''
    return f"""You are scoring the SPINE of a project at the event-list resolution.
The spine is an ordered event list (each row has id, title, summary,
function). Your job:

1. Score each event on the three Layer 1 per-event axes.
2. Score the spine as a whole on the five Layer 2 axes.
3. Surface every weak causal handoff (score below {WEAK_HANDOFF_THRESHOLD})
   and propose ONE concrete clause-level fix to the highest-leverage
   weak handoff.

Apply the function-appropriate concreteness floor: a midpoint reversal
scoring 7 on concreteness is at-ceiling for its function; an inciting
incident scoring 7 has lift available. Use the per-event floor noted
inline with each event below.

# Rubric

{rubric}

# Pitch context

## Logline
{artifacts.logline}

## Synopsis
{artifacts.synopsis}

## Theme
{artifacts.theme or '(empty)'}

# Act-shape

{act_shape_block}

# Spine events (in order)

{events_block}

# Task

Valid per-event axis keys: {per_event_axis_list}
Valid whole-spine axis keys: {spine_axis_list}

The final event ("{final_event_id}") has no causal handoff — omit
the causal_handoff row for that event entirely (do NOT include it
with score 0 or score null).

Return a JSON object with this exact shape:

{{
  "per_event": [
    {{
      "event_id": "<spine event id>",
      "scores": [
        {{"axis": "{PER_EVENT_AXES[0].key}", "score": 1-10 integer,
          "rationale": "one-sentence justification grounded in this event"}},
        ... one entry per per-event axis key (omit causal_handoff for the final event) ...
      ]
    }},
    ... one entry per spine event in spine order ...
  ],
  "whole_spine": [
    {{"axis": "{SPINE_AXES[0].key}",
      "score": 1-10 integer,
      "positive_signals": "semicolon-separated quoted signals across events",
      "negative_signals": "semicolon-separated quoted gaps across events",
      "rationale": "one-sentence justification"}},
    ... one entry per whole-spine axis key ...
  ],
  "spine_diagnostic": {{
    "lowest_axis": "name of the lowest-scoring axis across both layers",
    "lowest_axis_average": "the average score on that axis as a decimal",
    "summary": "one sentence: what the lowest axis tells you about the spine",
    "high_leverage_move": "one sentence: ONE specific clause-level change that would lift the most ground"
  }},
  "proposed_fix": {{
    "target_event_id": "the upstream event whose summary should be amended",
    "target_handoff": "<from_event_id> -> <to_event_id>",
    "current_summary_tail": "the last clause of the upstream summary as it stands now",
    "proposed_clause": "the 5-15 word clause to ADD to the upstream summary (no rewrite — additive only)",
    "expected_lift": "predicted axis-score lift in 'axis: was → now' form"
  }}
}}

Score per-event using the same 1-10 bands as the pitch rubric.
Reserve 10 for prose-verified excellence. Be specific and grounded —
quote the spine summaries. Return ONLY the JSON object.
"""


def _extract_per_event_scores(parsed: dict, event_ids: list[str]
                                ) -> dict[str, dict[str, int]]:
    """Pull {event_id: {axis_key: score}} from the spine response,
    dropping malformed / out-of-range / unknown rows (mirrors
    _extract_per_act_scores)."""
    valid_ids = set(event_ids)
    out: dict[str, dict[str, int]] = {eid: {} for eid in event_ids}
    drops: list[str] = []
    for ev_row in parsed.get('per_event') or []:
        if not isinstance(ev_row, dict):
            drops.append(f'non-dict per_event row: {ev_row!r}')
            continue
        event_id = ev_row.get('event_id')
        if event_id not in valid_ids:
            drops.append(f'unknown event_id={event_id!r}')
            continue
        for score_row in ev_row.get('scores') or []:
            if not isinstance(score_row, dict):
                drops.append(f'non-dict score row in {event_id}')
                continue
            axis = score_row.get('axis')
            if axis not in PER_EVENT_AXIS_BY_KEY:
                drops.append(f'unknown axis={axis!r} in {event_id}')
                continue
            try:
                score = int(score_row.get('score'))
            except (TypeError, ValueError):
                drops.append(
                    f'non-int score in {event_id}.{axis}: '
                    f'{score_row.get("score")!r}'
                )
                continue
            if not 1 <= score <= 10:
                drops.append(f'out-of-range score in {event_id}.{axis}: {score}')
                continue
            out[event_id][axis] = score
    if drops:
        shown = '; '.join(drops[:5])
        suffix = f' (and {len(drops) - 5} more)' if len(drops) > 5 else ''
        log(f'INFO: per-event extraction dropped {len(drops)} row(s): '
            f'{shown}{suffix}')
    return out


def _extract_whole_spine_scores(parsed: dict) -> WholeSpineScores:
    """Pull {axis_key: score} from the whole-spine response."""
    out: WholeSpineScores = {}
    drops: list[str] = []
    for row in parsed.get('whole_spine') or []:
        if not isinstance(row, dict):
            drops.append(f'non-dict whole_spine row: {row!r}')
            continue
        axis = row.get('axis')
        if axis not in SPINE_AXIS_BY_KEY:
            drops.append(f'unknown whole-spine axis={axis!r}')
            continue
        try:
            score = int(row.get('score'))
        except (TypeError, ValueError):
            drops.append(f'non-int whole-spine score in {axis}: '
                         f'{row.get("score")!r}')
            continue
        if not 1 <= score <= 10:
            drops.append(f'out-of-range whole-spine score in {axis}: {score}')
            continue
        out[axis] = score  # type: ignore[literal-required]
    if drops:
        shown = '; '.join(drops[:5])
        suffix = f' (and {len(drops) - 5} more)' if len(drops) > 5 else ''
        log(f'INFO: whole-spine extraction dropped {len(drops)} row(s): '
            f'{shown}{suffix}')
    return out


def _identify_weak_handoffs(events: list[SpineEvent],
                              per_event: dict[str, dict[str, int]],
                              threshold: int = WEAK_HANDOFF_THRESHOLD,
                              ) -> tuple[list[WeakHandoff], list[tuple[str, str]]]:
    """List transitions where upstream causal_handoff is below threshold.

    Returns (weak, skipped). `skipped` carries (from_event, to_event)
    pairs whose upstream had no causal_handoff score at all — surfacing
    these keeps the author from reading a clean weak-handoff list as
    "no problems found" when the analysis was actually incomplete.

    is_act_bridge is a heuristic (keyword match on the upstream's
    function); false negatives are acceptable — it's a surfacing hint.
    """
    weak: list[WeakHandoff] = []
    skipped: list[tuple[str, str]] = []
    for i in range(len(events) - 1):
        upstream = events[i]
        downstream = events[i + 1]
        score = per_event.get(upstream.id, {}).get('causal_handoff')
        if score is None:
            skipped.append((upstream.id, downstream.id))
            continue
        if score >= threshold:
            continue
        f = (upstream.function or '').lower()
        is_act_bridge = any(
            kw in f for kw in
            ('turning point', 'midpoint', 'act 1 closer', 'act 2 closer',
             'climax setup', 'climax')
        )
        weak.append({
            'from_event': upstream.id,
            'to_event': downstream.id,
            'score': score,
            'is_act_bridge': is_act_bridge,
        })
    return weak, skipped


def _parse_response_spine(text: str) -> dict | None:
    """Tolerant JSON parse for the spine payload. Same three-tier
    fallback as _parse_response_act_shape; shape check requires
    `per_event` AND `whole_spine` lists."""
    missing_fields: list[str] = []

    def _take(obj):
        if not isinstance(obj, dict):
            return None
        per_event = obj.get('per_event')
        whole_spine = obj.get('whole_spine')
        local_missing = []
        if not isinstance(per_event, list):
            local_missing.append('per_event')
        if not isinstance(whole_spine, list):
            local_missing.append('whole_spine')
        if local_missing:
            missing_fields[:] = local_missing
            return None
        return obj
    try:
        out = _take(json.loads(text))
        if out is not None:
            return out
    except json.JSONDecodeError:
        pass
    m = re.search(r'```(?:json)?\s*\n(.*?)\n```', text, re.DOTALL)
    if m:
        try:
            out = _take(json.loads(m.group(1).strip()))
            if out is not None:
                return out
        except json.JSONDecodeError:
            pass
    m = re.search(r'\{.*\}', text, re.DOTALL)
    if m:
        try:
            out = _take(json.loads(m.group(0)))
            if out is not None:
                return out
        except json.JSONDecodeError:
            pass
    if missing_fields:
        log(f'WARNING: spine LLM returned valid JSON but missing required '
            f'list(s): {", ".join(missing_fields)}.')
    return None


def _run_spine_extension(project_dir: str, output_dir: str, log_dir: str,
                           events: list[SpineEvent],
                           artifacts: PitchArtifacts,
                           act_shape: ActShape | None,
                           rubric: str,
                           coaching: CoachingLevel,
                           ) -> SpineExtension:
    """Run the spine-mode LLM call and write the spine CSVs.

    Always returns a SpineExtension; status carries the outcome.
    Pitch result (and act-shape extension) still stand on any failure.
    """
    prompt = _build_spine_prompt(events, artifacts, act_shape, rubric)
    model = select_model('creative')
    log_file = os.path.join(log_dir,
                            os.path.basename(output_dir) + '-spine.json')
    os.makedirs(log_dir, exist_ok=True)
    try:
        invoke_to_file(prompt, model, log_file, max_tokens=8192)
    except Exception as e:
        log(f'ERROR: spine LLM call failed: {e}. Pitch result still stands.')
        return _empty_spine_extension('llm_error')
    text = _read_response_text(log_file)
    parsed = _parse_response_spine(text)
    if not parsed:
        _record_cost(project_dir, log_file, model,
                     target='story-power:spine:unparseable')
        log(f'ERROR: spine LLM response unparseable; raw at {log_file}.')
        return _empty_spine_extension('unparseable')
    _record_cost(project_dir, log_file, model, target='story-power:spine')

    event_ids = [ev.id for ev in events]
    per_event = _extract_per_event_scores(parsed, event_ids)
    whole_spine = _extract_whole_spine_scores(parsed)
    spine_diag = parsed.get('spine_diagnostic') or {}
    proposed_fix = parsed.get('proposed_fix') or {}

    # Floor mirrors the act-shape extension: refuse to publish a matrix
    # with any empty row, not just a wholly-empty one. A CSV with sparse
    # cells reads as "score 0 / N/A" to downstream consumers — missing
    # files are clearer signal than half-empty tables.
    empty_events = [eid for eid in event_ids if not per_event.get(eid)]
    has_any_per_event = any(per_event.get(eid) for eid in event_ids)
    has_any_whole_spine = bool(whole_spine)
    if empty_events and has_any_per_event:
        log(f'ERROR: spine extraction produced zero valid scores for '
            f'{", ".join(empty_events)}; refusing to write '
            f'per-event-matrix.csv with empty row(s). Raw response: {log_file}')
    elif not has_any_per_event:
        log(f'ERROR: spine extraction produced zero valid per-event scores; '
            f'refusing to write per-event-matrix.csv. Raw response: {log_file}')
    if not has_any_whole_spine:
        log(f'ERROR: spine extraction produced zero valid whole-spine '
            f'scores; refusing to write whole-spine-axes.csv. Raw response: '
            f'{log_file}')

    weak_handoffs, skipped_handoffs = _identify_weak_handoffs(events, per_event)

    # Partial-extraction tagging. The final event has no causal handoff
    # so its expected per-event score count is 2 not 3.
    expected_per_event = 0
    for i, ev in enumerate(events):
        expected_per_event += 2 if i == len(events) - 1 else 3
    actual_per_event = sum(len(s) for s in per_event.values())
    missing_per_event = max(0, expected_per_event - actual_per_event)
    missing_spine_axes = [a.key for a in SPINE_AXES
                           if a.key not in whole_spine]

    status: StoryPowerStatus = 'ok'
    if missing_per_event or missing_spine_axes:
        status = 'partial'
        parts = []
        if missing_per_event:
            parts.append(f'{missing_per_event} per-event cell(s) missing')
        if missing_spine_axes:
            parts.append(
                f'{len(missing_spine_axes)} whole-spine axis/axes missing '
                f'({", ".join(missing_spine_axes)})'
            )
        log(f'WARNING: spine extraction partial — {"; ".join(parts)}.')
    if status == 'ok':
        assert per_event and whole_spine, (
            'spine extension status=ok requires non-empty per_event_scores '
            'and whole_spine_scores'
        )

    write_matrix = has_any_per_event and not empty_events
    write_whole_spine = has_any_whole_spine
    if coaching == 'full':
        if write_matrix:
            _write_per_event_matrix(output_dir, events, per_event,
                                      recover_hint=log_file)
        if write_whole_spine:
            _write_whole_spine_axes(output_dir, whole_spine, parsed,
                                      recover_hint=log_file)
        if write_matrix or write_whole_spine:
            _append_spine_diagnostic(output_dir, events, per_event,
                                       whole_spine, weak_handoffs,
                                       skipped_handoffs,
                                       spine_diag, proposed_fix,
                                       include_matrix=write_matrix,
                                       include_whole_spine=write_whole_spine)
    else:
        if write_matrix or write_whole_spine:
            _append_spine_coaching_brief(
                output_dir, events, per_event, whole_spine,
                weak_handoffs, skipped_handoffs,
                spine_diag, proposed_fix,
                include_matrix=write_matrix,
                include_whole_spine=write_whole_spine,
                recover_hint=log_file,
            )

    return {
        'status': status,
        'per_event_scores': per_event,
        'whole_spine_scores': whole_spine,
        'spine_diagnostic': spine_diag,
        'weak_handoffs': weak_handoffs,
        'proposed_fix': proposed_fix,
    }


# ---------------------------------------------------------------------------
# Spine writers
# ---------------------------------------------------------------------------

def _write_per_event_matrix(output_dir: str, events: list[SpineEvent],
                              per_event: dict[str, dict[str, int]],
                              *, recover_hint: str = '') -> None:
    """Write per-event-matrix.csv — one row per event, columns for the
    three per-event axes."""
    csv_path = os.path.join(output_dir, 'per-event-matrix.csv')
    headers = ['event_id', 'function'] + [a.key for a in PER_EVENT_AXES]
    lines = ['|'.join(headers)]
    for ev in events:
        scores = per_event.get(ev.id, {})
        row = [ev.id, ev.function or '']
        for axis in PER_EVENT_AXES:
            row.append(str(scores.get(axis.key, '')))
        lines.append('|'.join(_sanitize_cell(c) for c in row))
    _safe_write(csv_path, '\n'.join(lines) + '\n', recover_hint=recover_hint)


def _write_whole_spine_axes(output_dir: str, whole_spine: dict[str, int],
                              parsed: dict, *, recover_hint: str = '') -> None:
    """Write whole-spine-axes.csv — one row per Layer 2 axis with signals."""
    csv_path = os.path.join(output_dir, 'whole-spine-axes.csv')
    headers = ['axis', 'name', 'score', 'weight', 'positive_signals',
               'negative_signals', 'rationale']
    rows_by_axis = {r.get('axis'): r for r in parsed.get('whole_spine', [])
                    if isinstance(r, dict)}
    lines = ['|'.join(headers)]
    for axis in SPINE_AXES:
        row = rows_by_axis.get(axis.key, {})
        lines.append('|'.join(_sanitize_cell(c) for c in (
            axis.key,
            axis.name,
            str(whole_spine.get(axis.key, '')),
            str(axis.weight),
            row.get('positive_signals', ''),
            row.get('negative_signals', ''),
            row.get('rationale', ''),
        )))
    _safe_write(csv_path, '\n'.join(lines) + '\n', recover_hint=recover_hint)


def _spine_diagnostic_section(events: list[SpineEvent],
                                per_event: dict[str, dict[str, int]],
                                whole_spine: dict[str, int],
                                weak_handoffs: list[WeakHandoff],
                                skipped_handoffs: list[tuple[str, str]],
                                spine_diag: dict,
                                proposed_fix: dict, *,
                                include_matrix: bool = True,
                                include_whole_spine: bool = True,
                                ) -> list[str]:
    """Shared spine markdown section (full diagnostic.md + coach brief)."""
    out: list[str] = []
    if include_matrix:
        out.extend([
            '## Per-event matrix (spine Layer 1)',
            '',
            '| Event | Function | Alignment | Concreteness | Causal handoff |',
            '|---|---|---|---|---|',
        ])
        for ev in events:
            scores = per_event.get(ev.id, {})
            out.append(
                f'| {ev.id} | {ev.function or "—"} | '
                f'{scores.get("function_alignment", "–")} | '
                f'{scores.get("concreteness", "–")} | '
                f'{scores.get("causal_handoff", "–")} |'
            )
    if include_whole_spine:
        if out:
            out.append('')
        out.extend(['## Whole-spine axes (spine Layer 2)', '',
                    '| Axis | Score | Weight |', '|---|---|---|'])
        for axis in SPINE_AXES:
            s = whole_spine.get(axis.key, '–')
            out.append(f'| {axis.name} | {s} | {axis.weight} |')

    if weak_handoffs:
        out.extend(['', '## Weak causal handoffs (below threshold {})'
                    .format(WEAK_HANDOFF_THRESHOLD), ''])
        for h in weak_handoffs:
            tag = ' (act bridge)' if h['is_act_bridge'] else ''
            out.append(
                f'- **{h["from_event"]} → {h["to_event"]}**: '
                f'score {h["score"]}{tag}'
            )

    if skipped_handoffs:
        out.extend([
            '',
            '## Skipped causal handoffs',
            '',
            'These transitions had no causal_handoff score in the response, '
            'so the weak-handoff analysis is incomplete here:',
            '',
        ])
        for from_ev, to_ev in skipped_handoffs:
            out.append(f'- {from_ev} → {to_ev}')

    out.extend([
        '',
        '## Spine diagnostic',
        '',
        f'**Lowest axis:** {spine_diag.get("lowest_axis") or "(none identified)"} '
        f'({spine_diag.get("lowest_axis_average") or "?"})',
        '',
        f'**Summary:** {spine_diag.get("summary") or "(none identified)"}',
        '',
        f'**High-leverage move:** {spine_diag.get("high_leverage_move") or "(none proposed)"}',
        '',
    ])

    if proposed_fix:
        out.extend([
            '### Proposed fix',
            '',
            f'**Target handoff:** {proposed_fix.get("target_handoff", "—")}',
            '',
            f'**Target event:** {proposed_fix.get("target_event_id", "—")}',
            '',
            f'**Current summary tail:** {proposed_fix.get("current_summary_tail", "—")}',
            '',
            f'**Proposed clause to add:**',
            '',
            f'> {proposed_fix.get("proposed_clause", "(none)")}',
            '',
            f'**Expected lift:** {proposed_fix.get("expected_lift", "—")}',
            '',
        ])

    return out


def _append_spine_diagnostic(output_dir: str, events: list[SpineEvent],
                               per_event: dict[str, dict[str, int]],
                               whole_spine: dict[str, int],
                               weak_handoffs: list[WeakHandoff],
                               skipped_handoffs: list[tuple[str, str]],
                               spine_diag: dict,
                               proposed_fix: dict, *,
                               include_matrix: bool = True,
                               include_whole_spine: bool = True,
                               ) -> None:
    """Append the spine section to the existing diagnostic.md."""
    md_path = os.path.join(output_dir, 'diagnostic.md')
    if not os.path.isfile(md_path):
        log(f'WARNING: spine diagnostic could not be appended — '
            f'{md_path} does not exist (upstream pitch-diagnostic write '
            'likely failed). Spine scores were computed but their '
            'diagnostic narrative is lost.')
        return
    try:
        with open(md_path, encoding='utf-8') as f:
            existing = f.read()
    except OSError as e:
        log(f'WARNING: could not append spine diagnostic to {md_path}: {e}')
        return
    section = _spine_diagnostic_section(
        events, per_event, whole_spine, weak_handoffs, skipped_handoffs,
        spine_diag, proposed_fix,
        include_matrix=include_matrix,
        include_whole_spine=include_whole_spine,
    )
    _safe_write(md_path, existing + '\n' + '\n'.join(section) + '\n')


def _append_spine_coaching_brief(output_dir: str,
                                    events: list[SpineEvent],
                                    per_event: dict[str, dict[str, int]],
                                    whole_spine: dict[str, int],
                                    weak_handoffs: list[WeakHandoff],
                                    skipped_handoffs: list[tuple[str, str]],
                                    spine_diag: dict,
                                    proposed_fix: dict, *,
                                    include_matrix: bool = True,
                                    include_whole_spine: bool = True,
                                    recover_hint: str = '') -> None:
    """coach coaching: append spine sections to coaching-brief.md."""
    md_path = os.path.join(output_dir, 'coaching-brief.md')
    if not os.path.isfile(md_path):
        log(f'WARNING: spine coaching brief could not be appended — '
            f'{md_path} does not exist (upstream coach-brief write likely '
            'failed). Spine scores were computed but are not captured in '
            'the brief.')
        return
    try:
        with open(md_path, encoding='utf-8') as f:
            existing = f.read()
    except OSError as e:
        log(f'WARNING: could not append spine coaching brief to {md_path}: {e}')
        return
    section = _spine_diagnostic_section(
        events, per_event, whole_spine, weak_handoffs, skipped_handoffs,
        spine_diag, proposed_fix,
        include_matrix=include_matrix,
        include_whole_spine=include_whole_spine,
    )
    # Coach-mode prelude: same independence reminder pattern as the
    # act-shape brief — keep the proposed fix as a proposal, not a
    # directive.
    prelude = [
        '# Spine extension (LLM proposals — author confirms)',
        '',
        'Per-event matrix and whole-spine axes follow. The proposed '
        'fix is one author-considered option, not a directive — the '
        'author decides whether the bridge clause is the right move.',
        '',
    ]
    _safe_write(md_path,
                existing + '\n' + '\n'.join(prelude + section) + '\n',
                recover_hint=recover_hint)


# ---------------------------------------------------------------------------
# Architecture extension (Layer 1 per-scene + Layer 2 whole-architecture)
# ---------------------------------------------------------------------------

# Word-boundary regexes used to scan the scene *summary* for verbs
# of recognition or action — the deterministic pre-pass flags
# turning_point/action_sequel labels whose summary contains none.
_REVELATION_RE = re.compile(
    r'\b(?:realiz\w*|recogniz\w*|understand\w*|understood|'
    r'discover\w*|reveal\w*|sees?|saw|knows?|knew|'
    r'remember\w*|recall\w*|glimps\w*|perceiv\w*)\b'
)
_ACTION_RE = re.compile(
    r'\b(?:strik\w*|struck|attack\w*|fle\w*|flew|chas\w*|'
    r'fight\w*|fought|break\w*|broke|broken|leap\w*|leapt|'
    r'runs?|ran|shoot\w*|shot|grab\w*|push\w*|pull\w*|shov\w*)\b'
)


def _empty_architecture_extension(status: StoryPowerStatus) -> ArchitectureExtension:
    """Placeholder ArchitectureExtension for a failed run."""
    return {
        'status': status,
        'per_scene_scores': {},
        'whole_architecture_scores': {},
        'architecture_diagnostic': {},
        'field_findings': [],
        'proposed_field_updates': [],
        'proposed_scene_insertions': [],
    }


def _check_field_coherence_deterministic(scene: SceneRow
                                            ) -> list[FieldCoherenceFinding]:
    """Run high-confidence regex/keyword checks on a single scene's
    fields. Returns a list of findings — the LLM is then told about
    these as ground-truth signal and refines / contextualizes the rest.

    Only flags cases where a mismatch is structurally unambiguous (e.g.,
    `turning_point: revelation` with a summary containing zero
    recognition verbs). Higher-noise cases are left to the LLM.
    """
    findings: list[FieldCoherenceFinding] = []
    summary_lower = scene.summary.lower()
    turning_point_lower = scene.turning_point.lower()
    action_sequel_lower = scene.action_sequel.lower()
    value_shift = scene.value_shift.strip()

    # 1. turning_point names a revelation/recognition but summary has
    # no verb of recognition.
    if turning_point_lower and any(kw in turning_point_lower for kw in (
            'revelation', 'recognition', 'realization', 'discovery',
            'epiphany')):
        if not _REVELATION_RE.search(summary_lower):
            findings.append({
                'scene_id': scene.id,
                'field': 'turning_point',
                'issue': (
                    f"turning_point={scene.turning_point!r} signals a "
                    'recognition beat, but the summary contains no verb '
                    'of realization/recognition/discovery'
                ),
                'severity': 'high',
            })

    # 2. action_sequel starts with 'action' but summary reads as pure
    # reflection (no action verbs at all). Lower confidence — sequel
    # scenes can still contain action; only flag when the asymmetry is
    # extreme. Uses startswith for symmetry with _action_sequel_ratio.
    if action_sequel_lower.startswith('action'):
        if not _ACTION_RE.search(summary_lower):
            findings.append({
                'scene_id': scene.id,
                'field': 'action_sequel',
                'issue': (
                    f"action_sequel={scene.action_sequel!r} but the "
                    'summary contains no concrete action verbs — verify '
                    'the classification'
                ),
                'severity': 'medium',
            })

    # 3. value_shift names a net-positive ending (+/+, +/++, -/+) but
    # emotional_arc uses rupture/loss language. The schema is
    # start_polarity/end_polarity — only the END polarity tells you
    # whether the scene resolves positive or negative, so we check the
    # second half. A '+/-' (starts positive, ends negative) scene with
    # 'trust to rupture' is consistent, not contradictory.
    parts = value_shift.split('/', 1)
    ends_positive = len(parts) == 2 and parts[1].startswith('+')
    if ends_positive:
        arc_lower = scene.emotional_arc.lower()
        if any(kw in arc_lower for kw in
               ('rupture', 'loss', 'collapse', 'shatter')):
            findings.append({
                'scene_id': scene.id,
                'field': 'value_shift',
                'issue': (
                    f"value_shift={value_shift!r} (net-positive ending) "
                    f"contradicts emotional_arc={scene.emotional_arc!r} "
                    '(rupture/loss language)'
                ),
                'severity': 'high',
            })

    return findings


def _action_sequel_ratio(scenes: list[SceneRow]) -> tuple[int, int, float]:
    """Return (action_count, sequel_count, action_ratio). Values not
    starting with 'action'/'sequel' count as neither."""
    action = sum(1 for s in scenes
                 if s.action_sequel.strip().lower().startswith('action'))
    sequel = sum(1 for s in scenes
                 if s.action_sequel.strip().lower().startswith('sequel'))
    total = action + sequel
    ratio = (action / total) if total else 0.0
    return action, sequel, ratio


def _build_architecture_prompt(scenes: list[SceneRow],
                                  spine_events: list[SpineEvent],
                                  artifacts: PitchArtifacts,
                                  register: Register,
                                  deterministic_findings: list[FieldCoherenceFinding],
                                  rubric: str) -> str:
    """Assemble the architecture-mode LLM prompt. Inlines deterministic
    findings as ground-truth signal so the LLM refines rather than
    re-discovering them."""
    per_scene_axis_list = ', '.join(f'"{a.key}"' for a in PER_SCENE_AXES)
    arch_axis_list = ', '.join(f'"{a.key}"' for a in ARCHITECTURE_AXES)
    scenes_block = '\n'.join(
        f'### {s.id} (serves spine_event={s.spine_event or "(none)"})\n'
        f'  title: {s.title or "(none)"}\n'
        f'  action_sequel: {s.action_sequel or "(blank)"}\n'
        f'  emotional_arc: {s.emotional_arc or "(blank)"}\n'
        f'  value_at_stake: {s.value_at_stake or "(blank)"}\n'
        f'  value_shift: {s.value_shift or "(blank)"}\n'
        f'  turning_point: {s.turning_point or "(blank)"}\n'
        f'  summary: {s.summary}'
        for s in scenes
    )
    if spine_events:
        spine_block = '\n'.join(
            f'- {ev.id} ({ev.function or "no function"}): {ev.summary}'
            for ev in spine_events
        )
    else:
        spine_block = '(no spine.csv populated)'
    if deterministic_findings:
        det_block = '\n'.join(
            f'- {f["scene_id"]}.{f["field"]} [{f["severity"]}]: {f["issue"]}'
            for f in deterministic_findings
        )
    else:
        det_block = '(no deterministic findings — base your scoring on the LLM-only pass)'

    action_count, sequel_count, ratio = _action_sequel_ratio(scenes)
    unclassified_count = len(scenes) - action_count - sequel_count

    return f"""You are scoring the ARCHITECTURE of a project at the scene resolution.
Each scene has structured fields beyond its prose summary. Your job:

1. Per-scene Layer 1: score each scene on the two per-scene axes.
2. Whole-architecture Layer 2: score the architecture as a whole on
   the five whole-architecture axes.
3. Surface field-coherence problems and propose SPECIFIC field updates
   (which field, what new value).
4. Detect spine bridges that no architecture scene enacts and propose
   new sequel scenes with full field definitions.

The deterministic pre-pass already flagged the findings below — treat
these as ground-truth signal and use them to seed your field-coherence
scoring rather than re-discovering them.

# Rubric

{rubric}

# Pitch context (already scored)

## Logline
{artifacts.logline}

## Synopsis
{artifacts.synopsis}

## Theme
{artifacts.theme or '(empty)'}

# Spine events (for spine-event service axis)

{spine_block}

# Architecture scenes under evaluation

{scenes_block}

# Project register (for action/sequel rhythm axis)

Declared register: **{register}**
Current ratio: {action_count} action / {sequel_count} sequel
({ratio:.0%} action of {action_count + sequel_count} classified scenes;
{unclassified_count} of {len(scenes)} scenes are unclassified — if that
share is large, the ratio is unreliable; name this in register_assessment.)

Register-specific expected bands:
- thriller / action / fast / commercial: 60-80% action
- literary / decompressed / atmospheric / contemplative: 25-50% action
- balanced (default): 40-60% action

Score action_sequel_rhythm against the declared register's band.

# Deterministic field-coherence findings (pre-pass)

{det_block}

# Task

Valid per-scene axis keys: {per_scene_axis_list}
Valid whole-architecture axis keys: {arch_axis_list}

Return a JSON object with this exact shape:

{{
  "per_scene": [
    {{
      "scene_id": "<architecture scene id>",
      "scores": [
        {{"axis": "{PER_SCENE_AXES[0].key}", "score": 1-10 integer,
          "rationale": "one-sentence justification grounded in this scene"}},
        ... one entry per per-scene axis ...
      ]
    }},
    ... one entry per architecture scene in order ...
  ],
  "whole_architecture": [
    {{"axis": "{ARCHITECTURE_AXES[0].key}",
      "score": 1-10 integer,
      "positive_signals": "semicolon-separated quoted signals",
      "negative_signals": "semicolon-separated quoted gaps",
      "rationale": "one-sentence justification"}},
    ... one entry per whole-architecture axis ...
  ],
  "architecture_diagnostic": {{
    "lowest_axis": "name of the lowest-scoring axis across both layers",
    "lowest_axis_average": "the average on that axis as a decimal",
    "summary": "one sentence: what the lowest axis tells you about the architecture",
    "register_assessment": "one sentence: how the action/sequel ratio compares to the declared register",
    "high_leverage_move": "one sentence: ONE specific change that would lift the most ground"
  }},
  "field_findings": [
    {{"scene_id": "<id>", "field": "<field name>",
      "issue": "what's wrong",
      "severity": "high|medium|low"}}
  ],
  "proposed_field_updates": [
    {{"scene_id": "<id>", "field": "emotional_arc",
      "current_value": "<current field value>",
      "proposed_value": "<concrete new value>",
      "rationale": "one sentence: why this update fixes the coherence drop"}}
  ],
  "proposed_scene_insertions": [
    {{"insert_after": "<existing scene id>",
      "proposed_id": "<new scene id>",
      "spine_event": "<spine event id the new scene serves>",
      "action_sequel": "sequel",
      "emotional_arc": "<value>",
      "value_at_stake": "<value>",
      "value_shift": "<value>",
      "turning_point": "<value>",
      "summary": "one sentence: what happens in this scene",
      "rationale": "which axes this scene insertion would lift, in 'axis: was → now' form"}}
  ]
}}

Reserve 10 for prose-verified excellence. Be specific and grounded —
quote the architecture scenes. The proposed updates and insertions are
the most valuable output; treat them as concrete craft moves, not
abstract recommendations. Return ONLY the JSON object.
"""


def _extract_per_scene_scores(parsed: dict, scene_ids: list[str]
                                ) -> dict[str, dict[str, int]]:
    """Pull {scene_id: {axis_key: score}} from the architecture response,
    dropping malformed / out-of-range / unknown rows."""
    valid_ids = set(scene_ids)
    out: dict[str, dict[str, int]] = {sid: {} for sid in scene_ids}
    drops: list[str] = []
    for sc_row in parsed.get('per_scene') or []:
        if not isinstance(sc_row, dict):
            drops.append(f'non-dict per_scene row: {sc_row!r}')
            continue
        scene_id = sc_row.get('scene_id')
        if scene_id not in valid_ids:
            drops.append(f'unknown scene_id={scene_id!r}')
            continue
        for score_row in sc_row.get('scores') or []:
            if not isinstance(score_row, dict):
                drops.append(f'non-dict score row in {scene_id}')
                continue
            axis = score_row.get('axis')
            if axis not in PER_SCENE_AXIS_BY_KEY:
                drops.append(f'unknown axis={axis!r} in {scene_id}')
                continue
            try:
                score = int(score_row.get('score'))
            except (TypeError, ValueError):
                drops.append(
                    f'non-int score in {scene_id}.{axis}: '
                    f'{score_row.get("score")!r}'
                )
                continue
            if not 1 <= score <= 10:
                drops.append(f'out-of-range score in {scene_id}.{axis}: {score}')
                continue
            out[scene_id][axis] = score
    if drops:
        shown = '; '.join(drops[:5])
        suffix = f' (and {len(drops) - 5} more)' if len(drops) > 5 else ''
        log(f'INFO: per-scene extraction dropped {len(drops)} row(s): '
            f'{shown}{suffix}')
    return out


def _extract_whole_architecture_scores(parsed: dict) -> WholeArchitectureScores:
    """Pull {axis_key: score} from the whole-architecture response."""
    out: WholeArchitectureScores = {}
    drops: list[str] = []
    for row in parsed.get('whole_architecture') or []:
        if not isinstance(row, dict):
            drops.append(f'non-dict whole_architecture row: {row!r}')
            continue
        axis = row.get('axis')
        if axis not in ARCHITECTURE_AXIS_BY_KEY:
            drops.append(f'unknown whole-architecture axis={axis!r}')
            continue
        try:
            score = int(row.get('score'))
        except (TypeError, ValueError):
            drops.append(f'non-int whole-architecture score in {axis}: '
                         f'{row.get("score")!r}')
            continue
        if not 1 <= score <= 10:
            drops.append(
                f'out-of-range whole-architecture score in {axis}: {score}'
            )
            continue
        out[axis] = score  # type: ignore[literal-required]
    if drops:
        shown = '; '.join(drops[:5])
        suffix = f' (and {len(drops) - 5} more)' if len(drops) > 5 else ''
        log(f'INFO: whole-architecture extraction dropped {len(drops)} '
            f'row(s): {shown}{suffix}')
    return out


def _parse_response_architecture(text: str) -> dict | None:
    """Tolerant JSON parse for the architecture payload. Three-tier
    fallback; shape check requires `per_scene` AND `whole_architecture`
    lists."""
    missing_fields: list[str] = []

    def _take(obj):
        if not isinstance(obj, dict):
            return None
        per_scene = obj.get('per_scene')
        whole_arch = obj.get('whole_architecture')
        local_missing = []
        if not isinstance(per_scene, list):
            local_missing.append('per_scene')
        if not isinstance(whole_arch, list):
            local_missing.append('whole_architecture')
        if local_missing:
            missing_fields[:] = local_missing
            return None
        return obj
    try:
        out = _take(json.loads(text))
        if out is not None:
            return out
    except json.JSONDecodeError:
        pass
    m = re.search(r'```(?:json)?\s*\n(.*?)\n```', text, re.DOTALL)
    if m:
        try:
            out = _take(json.loads(m.group(1).strip()))
            if out is not None:
                return out
        except json.JSONDecodeError:
            pass
    m = re.search(r'\{.*\}', text, re.DOTALL)
    if m:
        try:
            out = _take(json.loads(m.group(0)))
            if out is not None:
                return out
        except json.JSONDecodeError:
            pass
    if missing_fields:
        log(f'WARNING: architecture LLM returned valid JSON but missing '
            f'required list(s): {", ".join(missing_fields)}.')
    return None


def _run_architecture_extension(project_dir: str, output_dir: str,
                                  log_dir: str,
                                  scenes: list[SceneRow],
                                  spine_events: list[SpineEvent],
                                  artifacts: PitchArtifacts,
                                  register: Register,
                                  rubric: str,
                                  coaching: CoachingLevel,
                                  ) -> ArchitectureExtension:
    """Run the architecture-mode LLM call (after the deterministic
    field-coherence pre-pass) and write the architecture CSVs.

    Returns an ArchitectureExtension; status carries the outcome. Pitch
    result still stands on any failure.
    """
    # Pre-pass costs no tokens and seeds the LLM with high-confidence
    # findings; preserved on the extension even if the LLM call fails.
    det_findings: list[FieldCoherenceFinding] = []
    for scene in scenes:
        det_findings.extend(_check_field_coherence_deterministic(scene))

    # WARN when more than half the scenes lack an action_sequel
    # classification — the rhythm axis will score against a small
    # denominator and the result may look decisive but be meaningless.
    action_count, sequel_count, _ = _action_sequel_ratio(scenes)
    unclassified = len(scenes) - action_count - sequel_count
    if scenes and unclassified / len(scenes) > 0.5:
        log(f'WARNING: {unclassified}/{len(scenes)} architecture scenes '
            f'lack an action_sequel classification; action_sequel_rhythm '
            f'will score against only {action_count + sequel_count} '
            'classified scenes. Run `storyforge hone` to fill the gaps.')

    prompt = _build_architecture_prompt(scenes, spine_events, artifacts,
                                          register, det_findings, rubric)
    model = select_model('creative')
    log_file = os.path.join(log_dir,
                            os.path.basename(output_dir) + '-architecture.json')
    os.makedirs(log_dir, exist_ok=True)
    try:
        invoke_to_file(prompt, model, log_file, max_tokens=8192)
    except Exception as e:
        log(f'ERROR: architecture LLM call failed: {e}. Pitch result still stands.')
        ext = _empty_architecture_extension('llm_error')
        ext['field_findings'] = det_findings  # preserve deterministic signal
        return ext
    text = _read_response_text(log_file)
    parsed = _parse_response_architecture(text)
    if not parsed:
        _record_cost(project_dir, log_file, model,
                     target='story-power:architecture:unparseable')
        log(f'ERROR: architecture LLM response unparseable; raw at {log_file}.')
        ext = _empty_architecture_extension('unparseable')
        ext['field_findings'] = det_findings
        return ext
    _record_cost(project_dir, log_file, model,
                 target='story-power:architecture')

    scene_ids = [s.id for s in scenes]
    per_scene = _extract_per_scene_scores(parsed, scene_ids)
    whole_arch = _extract_whole_architecture_scores(parsed)
    diag = parsed.get('architecture_diagnostic') or {}
    llm_findings = _extract_field_findings(parsed)
    proposed_updates = _extract_proposed_field_updates(parsed)
    proposed_inserts = _extract_proposed_scene_insertions(parsed)

    # Flag proposed insertion ids that collide with existing scenes —
    # otherwise an author who accepts the proposal naively would end
    # up with a duplicate id in architecture.csv.
    existing_ids = set(scene_ids)
    for ins in proposed_inserts:
        if ins['proposed_id'] in existing_ids:
            log(f'WARNING: proposed scene insertion id '
                f'{ins["proposed_id"]!r} collides with an existing '
                'architecture scene; the author must rename before '
                'accepting this proposal.')

    # Deterministic findings first — higher confidence; LLM may corroborate.
    field_findings = det_findings + llm_findings

    empty_scenes = [sid for sid in scene_ids if not per_scene.get(sid)]
    has_any_per_scene = any(per_scene.get(sid) for sid in scene_ids)
    has_any_whole_arch = bool(whole_arch)
    if empty_scenes and has_any_per_scene:
        log(f'ERROR: architecture extraction produced zero valid scores for '
            f'{", ".join(empty_scenes)}; refusing to write '
            f'per-scene-matrix.csv with empty row(s). Raw response: {log_file}')
    elif not has_any_per_scene:
        log(f'ERROR: architecture extraction produced zero valid per-scene '
            f'scores; refusing to write per-scene-matrix.csv. Raw response: '
            f'{log_file}')
    if not has_any_whole_arch:
        log(f'ERROR: architecture extraction produced zero valid '
            f'whole-architecture scores; refusing to write '
            f'whole-architecture-axes.csv. Raw response: {log_file}')

    # Partial-status: per-scene has 2 axes per scene, all expected.
    expected_per_scene = 2 * len(scenes)
    actual_per_scene = sum(len(s) for s in per_scene.values())
    missing_per_scene = max(0, expected_per_scene - actual_per_scene)
    missing_arch_axes = [a.key for a in ARCHITECTURE_AXES
                          if a.key not in whole_arch]
    status: StoryPowerStatus = 'ok'
    if missing_per_scene or missing_arch_axes:
        status = 'partial'
        parts = []
        if missing_per_scene:
            parts.append(f'{missing_per_scene} per-scene cell(s) missing')
        if missing_arch_axes:
            parts.append(
                f'{len(missing_arch_axes)} whole-architecture axis/axes '
                f'missing ({", ".join(missing_arch_axes)})'
            )
        log(f'WARNING: architecture extraction partial — {"; ".join(parts)}.')
    if status == 'ok':
        assert per_scene and whole_arch, (
            'architecture extension status=ok requires non-empty '
            'per_scene_scores and whole_architecture_scores'
        )

    write_matrix = has_any_per_scene and not empty_scenes
    write_whole_arch = has_any_whole_arch
    if coaching == 'full':
        if write_matrix:
            _write_per_scene_matrix(output_dir, scenes, per_scene,
                                      recover_hint=log_file)
        if write_whole_arch:
            _write_whole_architecture_axes(output_dir, whole_arch, parsed,
                                              recover_hint=log_file)
        if write_matrix or write_whole_arch:
            _append_architecture_diagnostic(
                output_dir, scenes, per_scene, whole_arch,
                field_findings, proposed_updates, proposed_inserts,
                diag, register,
                include_matrix=write_matrix,
                include_whole_arch=write_whole_arch,
            )
    else:
        if write_matrix or write_whole_arch:
            _append_architecture_coaching_brief(
                output_dir, scenes, per_scene, whole_arch,
                field_findings, proposed_updates, proposed_inserts,
                diag, register,
                include_matrix=write_matrix,
                include_whole_arch=write_whole_arch,
                recover_hint=log_file,
            )

    return {
        'status': status,
        'per_scene_scores': per_scene,
        'whole_architecture_scores': whole_arch,
        'architecture_diagnostic': diag,
        'field_findings': field_findings,
        'proposed_field_updates': proposed_updates,
        'proposed_scene_insertions': proposed_inserts,
    }


def _log_extraction_drops(name: str, drops: list[str]) -> None:
    """Emit one INFO line listing the first 5 drop reasons. The full
    raw response is on disk; this is just the localization breadcrumb."""
    if not drops:
        return
    shown = '; '.join(drops[:5])
    suffix = f' (and {len(drops) - 5} more)' if len(drops) > 5 else ''
    log(f'INFO: {name} extraction dropped {len(drops)} row(s): {shown}{suffix}')


def _extract_field_findings(parsed: dict) -> list[FieldCoherenceFinding]:
    """Pull LLM-provided field-coherence findings."""
    out: list[FieldCoherenceFinding] = []
    drops: list[str] = []
    for row in parsed.get('field_findings') or []:
        if not isinstance(row, dict):
            drops.append(f'non-dict row: {row!r}')
            continue
        scene_id = row.get('scene_id', '').strip()
        field = row.get('field', '').strip()
        issue = row.get('issue', '').strip()
        missing = [name for name, val in
                   (('scene_id', scene_id), ('field', field),
                    ('issue', issue))
                   if not val]
        if missing:
            drops.append(f'incomplete row (scene_id={scene_id!r}, '
                         f'missing: {",".join(missing)})')
            continue
        raw_severity = row.get('severity', 'medium').strip().lower()
        severity: Severity = (
            raw_severity if raw_severity in ('high', 'medium', 'low')
            else 'medium'
        )  # type: ignore[assignment]
        out.append({
            'scene_id': scene_id,
            'field': field,
            'issue': issue,
            'severity': severity,
        })
    _log_extraction_drops('field_findings', drops)
    return out


def _extract_proposed_field_updates(parsed: dict) -> list[ProposedFieldUpdate]:
    """Pull LLM-proposed field updates. Tolerant of missing optional fields."""
    out: list[ProposedFieldUpdate] = []
    drops: list[str] = []
    for row in parsed.get('proposed_field_updates') or []:
        if not isinstance(row, dict):
            drops.append(f'non-dict row: {row!r}')
            continue
        scene_id = row.get('scene_id', '').strip()
        field = row.get('field', '').strip()
        proposed_value = row.get('proposed_value', '').strip()
        missing = [name for name, val in
                   (('scene_id', scene_id), ('field', field),
                    ('proposed_value', proposed_value))
                   if not val]
        if missing:
            drops.append(f'incomplete row (scene_id={scene_id!r}, '
                         f'missing: {",".join(missing)})')
            continue
        out.append({
            'scene_id': scene_id,
            'field': field,
            'current_value': row.get('current_value', '').strip(),
            'proposed_value': proposed_value,
            'rationale': row.get('rationale', '').strip(),
        })
    _log_extraction_drops('proposed_field_updates', drops)
    return out


def _extract_proposed_scene_insertions(parsed: dict
                                         ) -> list[ProposedSceneInsertion]:
    """Pull LLM-proposed scene insertions."""
    out: list[ProposedSceneInsertion] = []
    drops: list[str] = []
    for row in parsed.get('proposed_scene_insertions') or []:
        if not isinstance(row, dict):
            drops.append(f'non-dict row: {row!r}')
            continue
        insert_after = row.get('insert_after', '').strip()
        proposed_id = row.get('proposed_id', '').strip()
        summary = row.get('summary', '').strip()
        missing = [name for name, val in
                   (('insert_after', insert_after),
                    ('proposed_id', proposed_id), ('summary', summary))
                   if not val]
        if missing:
            drops.append(f'incomplete row (proposed_id={proposed_id!r}, '
                         f'missing: {",".join(missing)})')
            continue
        out.append({
            'insert_after': insert_after,
            'proposed_id': proposed_id,
            'spine_event': row.get('spine_event', '').strip(),
            'action_sequel': row.get('action_sequel', '').strip(),
            'emotional_arc': row.get('emotional_arc', '').strip(),
            'value_at_stake': row.get('value_at_stake', '').strip(),
            'value_shift': row.get('value_shift', '').strip(),
            'turning_point': row.get('turning_point', '').strip(),
            'summary': summary,
            'rationale': row.get('rationale', '').strip(),
        })
    _log_extraction_drops('proposed_scene_insertions', drops)
    return out


# ---------------------------------------------------------------------------
# Architecture writers
# ---------------------------------------------------------------------------

def _write_per_scene_matrix(output_dir: str, scenes: list[SceneRow],
                              per_scene: dict[str, dict[str, int]],
                              *, recover_hint: str = '') -> None:
    """Write per-scene-matrix.csv — one row per scene, columns for the
    two per-scene axes (spine_event_service, field_coherence)."""
    csv_path = os.path.join(output_dir, 'per-scene-matrix.csv')
    headers = (['scene_id', 'spine_event']
               + [a.key for a in PER_SCENE_AXES])
    lines = ['|'.join(headers)]
    for scene in scenes:
        scores = per_scene.get(scene.id, {})
        row = [scene.id, scene.spine_event or '']
        for axis in PER_SCENE_AXES:
            row.append(str(scores.get(axis.key, '')))
        lines.append('|'.join(_sanitize_cell(c) for c in row))
    _safe_write(csv_path, '\n'.join(lines) + '\n', recover_hint=recover_hint)


def _write_whole_architecture_axes(output_dir: str,
                                      whole_arch: WholeArchitectureScores,
                                      parsed: dict, *,
                                      recover_hint: str = '') -> None:
    """Write whole-architecture-axes.csv — one row per Layer 2 axis."""
    csv_path = os.path.join(output_dir, 'whole-architecture-axes.csv')
    headers = ['axis', 'name', 'score', 'weight', 'positive_signals',
               'negative_signals', 'rationale']
    rows_by_axis = {r.get('axis'): r for r in parsed.get('whole_architecture', [])
                    if isinstance(r, dict)}
    lines = ['|'.join(headers)]
    for axis in ARCHITECTURE_AXES:
        row = rows_by_axis.get(axis.key, {})
        lines.append('|'.join(_sanitize_cell(c) for c in (
            axis.key,
            axis.name,
            str(whole_arch.get(axis.key, '')),
            str(axis.weight),
            row.get('positive_signals', ''),
            row.get('negative_signals', ''),
            row.get('rationale', ''),
        )))
    _safe_write(csv_path, '\n'.join(lines) + '\n', recover_hint=recover_hint)


def _architecture_diagnostic_section(
        scenes: list[SceneRow],
        per_scene: dict[str, dict[str, int]],
        whole_arch: WholeArchitectureScores,
        field_findings: list[FieldCoherenceFinding],
        proposed_updates: list[ProposedFieldUpdate],
        proposed_inserts: list[ProposedSceneInsertion],
        diag: ArchitectureDiagnostic,
        register: Register, *,
        include_matrix: bool = True,
        include_whole_arch: bool = True,
        ) -> list[str]:
    """Shared architecture markdown section (full diagnostic.md + coach brief)."""
    out: list[str] = []
    if include_matrix:
        out.extend([
            '## Per-scene matrix (architecture Layer 1)',
            '',
            '| Scene | Spine event | Service | Field coherence |',
            '|---|---|---|---|',
        ])
        for s in scenes:
            sc = per_scene.get(s.id, {})
            out.append(
                f'| {s.id} | {s.spine_event or "—"} | '
                f'{sc.get("spine_event_service", "–")} | '
                f'{sc.get("field_coherence", "–")} |'
            )
    if include_whole_arch:
        if out:
            out.append('')
        out.extend([
            '## Whole-architecture axes (architecture Layer 2)',
            '',
            '| Axis | Score | Weight |',
            '|---|---|---|',
        ])
        for axis in ARCHITECTURE_AXES:
            s = whole_arch.get(axis.key, '–')
            out.append(f'| {axis.name} | {s} | {axis.weight} |')

    if field_findings:
        out.extend(['', '## Field-coherence findings', ''])
        for f in field_findings:
            out.append(
                f'- **{f["scene_id"]}** [{f["severity"]}] '
                f'`{f["field"]}`: {f["issue"]}'
            )

    if proposed_updates:
        out.extend(['', '## Proposed field updates', ''])
        for u in proposed_updates:
            out.extend([
                f'### {u["scene_id"]}.`{u["field"]}`',
                '',
                f'**Current:** {u.get("current_value") or "(blank)"}',
                '',
                f'**Proposed:** {u.get("proposed_value", "—")}',
                '',
                f'**Rationale:** {u.get("rationale") or "(none provided)"}',
                '',
            ])

    if proposed_inserts:
        out.extend(['', '## Proposed scene insertions', ''])
        for ins in proposed_inserts:
            out.extend([
                f'### Insert after {ins["insert_after"]}: {ins["proposed_id"]}',
                '',
                f'- **spine_event:** {ins.get("spine_event") or "—"}',
                f'- **action_sequel:** {ins.get("action_sequel") or "—"}',
                f'- **emotional_arc:** {ins.get("emotional_arc") or "—"}',
                f'- **value_at_stake:** {ins.get("value_at_stake") or "—"}',
                f'- **value_shift:** {ins.get("value_shift") or "—"}',
                f'- **turning_point:** {ins.get("turning_point") or "—"}',
                '',
                f'**Summary:** {ins["summary"]}',
                '',
                f'**Rationale:** {ins.get("rationale") or "(none provided)"}',
                '',
            ])

    out.extend([
        '',
        '## Architecture diagnostic',
        '',
        f'**Declared register:** {register}',
        '',
        f'**Register assessment:** {diag.get("register_assessment") or "(none provided)"}',
        '',
        f'**Lowest axis:** {diag.get("lowest_axis") or "(none identified)"} '
        f'({diag.get("lowest_axis_average") or "?"})',
        '',
        f'**Summary:** {diag.get("summary") or "(none identified)"}',
        '',
        f'**High-leverage move:** {diag.get("high_leverage_move") or "(none proposed)"}',
        '',
    ])

    return out


def _append_architecture_diagnostic(
        output_dir: str, scenes: list[SceneRow],
        per_scene: dict[str, dict[str, int]],
        whole_arch: WholeArchitectureScores,
        field_findings: list[FieldCoherenceFinding],
        proposed_updates: list[ProposedFieldUpdate],
        proposed_inserts: list[ProposedSceneInsertion],
        diag: ArchitectureDiagnostic,
        register: Register, *,
        include_matrix: bool = True,
        include_whole_arch: bool = True,
        ) -> None:
    """Append the architecture section to the existing diagnostic.md."""
    md_path = os.path.join(output_dir, 'diagnostic.md')
    if not os.path.isfile(md_path):
        log(f'WARNING: architecture diagnostic could not be appended — '
            f'{md_path} does not exist (upstream pitch-diagnostic write '
            'likely failed). Architecture scores were computed but their '
            'diagnostic narrative is lost.')
        return
    try:
        with open(md_path, encoding='utf-8') as f:
            existing = f.read()
    except OSError as e:
        log(f'WARNING: could not append architecture diagnostic to {md_path}: {e}')
        return
    section = _architecture_diagnostic_section(
        scenes, per_scene, whole_arch, field_findings,
        proposed_updates, proposed_inserts, diag, register,
        include_matrix=include_matrix,
        include_whole_arch=include_whole_arch,
    )
    _safe_write(md_path, existing + '\n' + '\n'.join(section) + '\n')


def _append_architecture_coaching_brief(
        output_dir: str, scenes: list[SceneRow],
        per_scene: dict[str, dict[str, int]],
        whole_arch: WholeArchitectureScores,
        field_findings: list[FieldCoherenceFinding],
        proposed_updates: list[ProposedFieldUpdate],
        proposed_inserts: list[ProposedSceneInsertion],
        diag: ArchitectureDiagnostic,
        register: Register, *,
        include_matrix: bool = True,
        include_whole_arch: bool = True,
        recover_hint: str = '',
        ) -> None:
    """coach coaching: append architecture sections to coaching-brief.md."""
    md_path = os.path.join(output_dir, 'coaching-brief.md')
    if not os.path.isfile(md_path):
        log(f'WARNING: architecture coaching brief could not be appended — '
            f'{md_path} does not exist (upstream coach-brief write likely '
            'failed). Architecture scores were computed but are not '
            'captured in the brief.')
        return
    try:
        with open(md_path, encoding='utf-8') as f:
            existing = f.read()
    except OSError as e:
        log(f'WARNING: could not append architecture coaching brief to '
            f'{md_path}: {e}')
        return
    section = _architecture_diagnostic_section(
        scenes, per_scene, whole_arch, field_findings,
        proposed_updates, proposed_inserts, diag, register,
        include_matrix=include_matrix,
        include_whole_arch=include_whole_arch,
    )
    prelude = [
        '# Architecture extension (LLM proposals — author confirms)',
        '',
        'Proposed field updates and scene insertions are concrete craft '
        'moves, not directives — the author decides whether each is the '
        'right move at this stage of the manuscript.',
        '',
    ]
    _safe_write(md_path,
                existing + '\n' + '\n'.join(prelude + section) + '\n',
                recover_hint=recover_hint)
