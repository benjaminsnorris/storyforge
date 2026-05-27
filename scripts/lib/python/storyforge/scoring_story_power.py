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


class WholeSceneMapScores(TypedDict, total=False):
    """Closed-key Layer 2 scene-map axis scores."""
    coverage_completeness: int
    pov_rotation: int
    pacing_distribution: int
    timeline_flow: int
    interstitial_economy: int


class _ContinuityFindingRequired(TypedDict):
    scene_id: str
    field: str
    issue: str
    severity: Severity


class ContinuityFinding(_ContinuityFindingRequired, total=False):
    """A scene-map continuity problem from the deterministic pre-pass
    or the LLM. preceding_id is present only for adjacency findings
    (transition between two scenes); absent for per-row findings."""
    preceding_id: str


SceneOperation = Literal['merge', 'split', 'insert', 'reorder', 'promote']
SCENE_OPERATIONS: tuple[SceneOperation, ...] = (
    'merge', 'split', 'insert', 'reorder', 'promote',
)
# Required scene_ids arity per operation — enforced at extraction.
# merge/reorder act on a pair; split/insert/promote act on a single row.
SCENE_OPERATION_ARITY: dict[SceneOperation, int] = {
    'merge': 2,
    'reorder': 2,
    'split': 1,
    'insert': 1,
    'promote': 1,
}


class _ProposedSceneOperationRequired(TypedDict):
    operation: SceneOperation
    scene_ids: list[str]
    summary: str


class ProposedSceneOperation(_ProposedSceneOperationRequired, total=False):
    """A concrete structural change the diagnostic proposes. Arity is
    enforced via SCENE_OPERATION_ARITY at extraction time. The author
    reviews and accepts / edits / rejects each proposal."""
    rationale: str


class SceneMapDiagnostic(TypedDict, total=False):
    """LLM-provided cross-axis pattern + coverage assessment."""
    lowest_axis: str
    lowest_axis_average: str
    summary: str
    coverage_assessment: str
    high_leverage_move: str


class SceneMapExtension(TypedDict):
    """Scene-map mode payload (Layer 1 + Layer 2 scores, continuity
    findings, and the LLM's proposed scene operations)."""
    per_scene_scores: dict[str, dict[str, int]]
    whole_scene_map_scores: WholeSceneMapScores
    scene_map_diagnostic: SceneMapDiagnostic
    continuity_findings: list[ContinuityFinding]
    proposed_operations: list[ProposedSceneOperation]
    status: StoryPowerStatus


class WholeBriefsScores(TypedDict, total=False):
    """Closed-key Layer 2 briefs axis scores."""
    outcome_distribution: int
    knowledge_flow_continuity: int
    crisis_density: int
    subtext_presence: int
    motif_recurrence: int


class _BriefFindingRequired(TypedDict):
    scene_id: str
    field: str
    issue: str
    severity: Severity


class BriefFinding(_BriefFindingRequired, total=False):
    """A brief-level problem flagged by the deterministic pre-pass or
    the LLM. `preceding_id` is optional: the deterministic pre-pass
    sets it on orphan-knowledge findings to the brief's first
    `continuity_deps` entry (the closest ancestor where the missing
    fact would have been expected); the LLM may set it on any finding
    where it wants to pin a related scene. Absent when no related
    scene is meaningful (e.g., missing-field findings, motif
    singletons, broken-dep findings)."""
    preceding_id: str


class _ProposedBriefUpdateRequired(TypedDict):
    scene_id: str
    field: str
    proposed_value: str


class ProposedBriefUpdate(_ProposedBriefUpdateRequired, total=False):
    """A concrete brief-field fix the diagnostic proposes. scene_id,
    field, and proposed_value are required (extractor drops rows
    missing any); current_value and rationale are LLM-optional."""
    current_value: str
    rationale: str


class BriefsDiagnostic(TypedDict, total=False):
    """LLM-provided cross-axis pattern at the briefs resolution."""
    lowest_axis: str
    lowest_axis_average: str
    summary: str
    scene_engine_assessment: str
    high_leverage_move: str


class BriefsExtension(TypedDict):
    """Briefs-mode payload (Layer 1 + Layer 2 scores, brief findings,
    and the LLM's proposed field updates)."""
    per_brief_scores: dict[str, dict[str, int]]
    whole_briefs_scores: WholeBriefsScores
    briefs_diagnostic: BriefsDiagnostic
    brief_findings: list[BriefFinding]
    proposed_brief_updates: list[ProposedBriefUpdate]
    status: StoryPowerStatus


# Cross-tier meta-diagnostic — synthesizes patterns across the six
# tier outputs. Distinct from any single tier; doesn't add axes (so
# no entry in _AXIS_FAMILIES) — its output is diagnostic + action
# prose, not numeric scores.

CrossTierPatternKey = Literal[
    'lowest_axis_recurrence',
    'scene_id_overlap',
    'field_coherence_cascade',
    'project_disposition',
]
CROSS_TIER_PATTERN_KEYS: tuple[CrossTierPatternKey, ...] = (
    'lowest_axis_recurrence',
    'scene_id_overlap',
    'field_coherence_cascade',
    'project_disposition',
)


class _CrossTierPatternRequired(TypedDict):
    pattern: CrossTierPatternKey
    description: str
    severity: Severity


class CrossTierPattern(_CrossTierPatternRequired, total=False):
    """A deterministic cross-tier pattern that fired in the pre-pass.

    `affected_tiers` names which tier outputs the pattern touches
    (e.g. ['architecture', 'briefs']); `affected_ids` names the
    concrete axis names, scene ids, or substrings that triggered
    the pattern. Both are optional because some patterns
    (e.g. project_disposition) describe the whole result rather than
    a specific axis/scene set."""
    affected_tiers: list[str]
    affected_ids: list[str]


class _CrossTierProposalRequired(TypedDict):
    target: str
    move: str


class CrossTierProposal(_CrossTierProposalRequired, total=False):
    """One high-leverage cross-tier move the LLM proposes.

    `target` is the locus the move acts on, formatted as a
    typed identifier (e.g. 'spine_event:ev-3', 'scene:s10',
    'tier:architecture'). `move` is a one-sentence action.

    `expected_lift` names which axes should rise and by how much;
    `consolidates_tiers` names tier-level proposals this supersedes
    so the author knows which downstream proposals to defer until
    after this move."""
    rationale: str
    expected_lift: str
    consolidates_tiers: list[str]


class CrossTierDiagnostic(TypedDict, total=False):
    """LLM-provided cross-tier pattern synthesis.

    All fields are optional because the LLM may omit any of them
    when the cross-tier signal is weak (a perfectly-scoring project
    has nothing to synthesize). The deterministic pre-pass output
    (`deterministic_patterns`) is the load-bearing surface; this is
    the narrative layer."""
    synthesis: str
    root_cause: str
    project_disposition: str
    high_leverage_move: str


class CrossTierExtension(TypedDict):
    """Cross-tier meta-diagnostic payload.

    `deterministic_patterns` always carries whatever the pre-pass
    detected (even when the LLM call fails); `proposals` and
    `cross_tier_diagnostic` come from the LLM synthesis when
    status='ok' or 'partial'."""
    deterministic_patterns: list[CrossTierPattern]
    proposals: list[CrossTierProposal]
    cross_tier_diagnostic: CrossTierDiagnostic
    status: StoryPowerStatus


class StoryPowerResult(TypedDict):
    """Result of score_story_power. Coaching is the requested level; status
    is the outcome. Output_dir is the timestamped directory written to
    (empty string when no directory was allocated).

    act_shape, spine, architecture, scene_map, and briefs are None when
    their inputs weren't present (no `## Act-shape` populated, no
    spine.csv / architecture.csv / scenes.csv / scene-briefs.csv on
    disk) or the extension failed before producing usable data;
    otherwise they carry the payload from each Layer 1/2 scoring run.

    cross_tier is None when fewer than 2 tier outputs are available
    (single-tier projects have nothing to synthesize across) or the
    deterministic pre-pass found nothing AND the LLM call failed.
    Otherwise carries the synthesis payload.
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
    scene_map: SceneMapExtension | None
    briefs: BriefsExtension | None
    cross_tier: CrossTierExtension | None


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


# Per-scene-map axes (scene-map Layer 1). continuity_coherence is the
# load-bearing axis — no other mode catches scene→scene adjacency
# (pov / location / timeline_day / type continuity).
PER_MAP_SCENE_AXES: tuple[Axis, ...] = (
    Axis('architecture_coverage', 'Architecture coverage', 1.0),
    Axis('continuity_coherence', 'Continuity coherence', 1.5),
)
PER_MAP_SCENE_AXIS_KEYS = tuple(a.key for a in PER_MAP_SCENE_AXES)
PER_MAP_SCENE_AXIS_BY_KEY = {a.key: a for a in PER_MAP_SCENE_AXES}

# Whole-scene-map axes (scene-map Layer 2).
MAP_AXES: tuple[Axis, ...] = (
    Axis('coverage_completeness', 'Coverage completeness', 1.5),
    Axis('pov_rotation', 'POV rotation', 1.0),
    Axis('pacing_distribution', 'Pacing distribution', 1.5),
    Axis('timeline_flow', 'Timeline flow', 1.0),
    Axis('interstitial_economy', 'Interstitial economy', 1.0),
)
MAP_AXIS_KEYS = tuple(a.key for a in MAP_AXES)
MAP_AXIS_BY_KEY = {a.key: a for a in MAP_AXES}

assert len({a.key for a in PER_MAP_SCENE_AXES}) == len(PER_MAP_SCENE_AXES), (
    'per-scene-map axis keys must be unique'
)
assert len({a.key for a in MAP_AXES}) == len(MAP_AXES), (
    'whole-scene-map axis keys must be unique'
)


# Per-brief axes (briefs Layer 1). scene_engine_integrity is the
# load-bearing axis — briefs exist to encode goal→conflict→outcome→
# crisis→decision, and no other mode scores that chain.
PER_BRIEF_AXES: tuple[Axis, ...] = (
    Axis('scene_engine_integrity', 'Scene-engine integrity', 1.5),
    Axis('concreteness_brief', 'Concreteness (brief)', 1.0),
)
PER_BRIEF_AXIS_KEYS = tuple(a.key for a in PER_BRIEF_AXES)
PER_BRIEF_AXIS_BY_KEY = {a.key: a for a in PER_BRIEF_AXES}

# Whole-briefs axes (briefs Layer 2). knowledge_flow_continuity is the
# unique-and-load-bearing axis — only briefs track per-scene knowledge
# state, so it's the only place where the fact-provenance graph can
# be scored.
BRIEFS_AXES: tuple[Axis, ...] = (
    Axis('outcome_distribution', 'Outcome distribution', 1.5),
    Axis('knowledge_flow_continuity', 'Knowledge-flow continuity', 1.5),
    Axis('crisis_density', 'Crisis density', 1.0),
    Axis('subtext_presence', 'Subtext presence', 1.0),
    Axis('motif_recurrence', 'Motif recurrence', 1.0),
)
BRIEFS_AXIS_KEYS = tuple(a.key for a in BRIEFS_AXES)
BRIEFS_AXIS_BY_KEY = {a.key: a for a in BRIEFS_AXES}

assert len({a.key for a in PER_BRIEF_AXES}) == len(PER_BRIEF_AXES), (
    'per-brief axis keys must be unique'
)
assert len({a.key for a in BRIEFS_AXES}) == len(BRIEFS_AXES), (
    'whole-briefs axis keys must be unique'
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
    ('per_map_scene', PER_MAP_SCENE_AXIS_KEYS),
    ('whole_scene_map', MAP_AXIS_KEYS),
    ('per_brief', PER_BRIEF_AXIS_KEYS),
    ('whole_briefs', BRIEFS_AXIS_KEYS),
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


# Brief outcomes form a closed enum per the schema (see
# schema.VALID_OUTCOMES). The Literal narrows static checks (e.g.
# `outcome == 'yes-but'` is statically verifiable as reachable);
# VALID_BRIEF_OUTCOMES retains the runtime membership set the
# deterministic pre-pass uses to flag invalid values.
BriefOutcome = Literal['yes', 'no', 'yes-but', 'no-and']
VALID_BRIEF_OUTCOMES: frozenset[BriefOutcome] = frozenset({
    'yes', 'no', 'yes-but', 'no-and',
})


class Brief(NamedTuple):
    """A scene-briefs.csv row. Array fields are `;`-split tuples.

    Construct with keyword args only — CSV column order is not guaranteed
    to match this tuple's positional order, so `Brief(*csv_row)` would
    silently misalign."""
    id: str
    goal: str
    conflict: str
    outcome: str
    crisis: str
    decision: str
    knowledge_in: tuple[str, ...]
    knowledge_out: tuple[str, ...]
    key_actions: str
    key_dialogue: str
    emotions: str
    motifs: tuple[str, ...]
    subtext: str
    continuity_deps: tuple[str, ...]


class MappedScene(NamedTuple):
    """A single row from reference/scenes.csv carrying the columns
    scene-map scoring consumes."""
    id: str
    seq: int | None             # None when the cell is blank or non-int
    title: str
    summary: str
    pov: str
    location: str
    timeline_day: str
    time_of_day: str
    scene_type: str             # 'type' is reserved; named scene_type here
    word_count: int             # 0 when blank
    target_words: int           # 0 when blank
    architecture_scene: str     # empty for interstitials


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


def parse_scene_map(project_dir: str) -> list[MappedScene]:
    """Read reference/scenes.csv as a seq-ordered list of MappedScene.

    Required columns: id, summary. All other scene-map columns (seq,
    title, pov, location, timeline_day, time_of_day, type, word_count,
    target_words, architecture_scene) are optional with sensible
    defaults. Returns [] when the file is missing or lacks the
    required columns. Sorts by seq when present; falls back to CSV
    row order when seq is missing or non-int."""
    csv_path = os.path.join(project_dir, 'reference', 'scenes.csv')
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
    required = {'id', 'summary'}
    if not required.issubset(set(headers)):
        log(f'WARNING: scenes.csv missing required columns; have '
            f'{headers}, need {sorted(required)}. Skipping scene-map mode.')
        return []
    rows: list[tuple[int, int, MappedScene]] = []  # (seq, row_index, scene)
    for i, line in enumerate(lines[1:], start=1):
        cells = line.split('|')
        if len(cells) != len(headers):
            log(f'WARNING: skipping malformed scenes.csv row {i} in '
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
            log(f'WARNING: scenes.csv row {i} missing required field(s) '
                f'{", ".join(missing)}; skipping. '
                f'(id={scene_id or "<blank>"})')
            continue

        def _as_int(col: str) -> int:
            try:
                return int(row.get(col, '').strip() or '0')
            except (TypeError, ValueError):
                return 0

        seq_raw = row.get('seq', '').strip()
        if not seq_raw:
            seq_val: int | None = None
        else:
            try:
                seq_val = int(seq_raw)
            except (TypeError, ValueError):
                log(f'WARNING: scenes.csv row {i} has non-int seq='
                    f'{seq_raw!r}; treating as unset')
                seq_val = None

        scene = MappedScene(
            id=scene_id,
            seq=seq_val,
            title=row.get('title', '').strip(),
            summary=summary,
            pov=row.get('pov', '').strip(),
            location=row.get('location', '').strip(),
            timeline_day=row.get('timeline_day', '').strip(),
            time_of_day=row.get('time_of_day', '').strip(),
            scene_type=row.get('type', '').strip(),
            word_count=_as_int('word_count'),
            target_words=_as_int('target_words'),
            architecture_scene=row.get('architecture_scene', '').strip(),
        )
        rows.append((scene.seq, i, scene))
    # Sort key: scenes with seq=None go to the end (preserving CSV
    # order within the unset group). The previous int+0-sentinel sort
    # put unset-seq scenes at the top — silently wrong for mixed cases
    # where some rows had explicit seq and others didn't.
    rows.sort(key=lambda r: (r[0] is None, r[0] if r[0] is not None else 0, r[1]))
    return [r[2] for r in rows]


def parse_scene_briefs(project_dir: str) -> list[Brief]:
    """Read reference/scene-briefs.csv as a list of Brief in CSV order.

    Returns [] when the file is missing, empty, or lacks the required
    `id` column. Briefs with empty `id` are dropped with a WARNING.
    Briefs with all five scene-engine fields empty are dropped with an
    INFO log — they're scaffolding rows from migration, expected
    during elaboration. (WARNING would be misleading since this is the
    intended steady-state for pre-briefed scenes; if the parent scene
    declares status>=briefed, the right escalation is in upstream
    validation, not here.)

    Array fields (knowledge_in, knowledge_out, motifs, continuity_deps)
    are split on `;`. Empty cells produce empty tuples.

    Order in the returned list mirrors CSV row order. Callers that need
    seq-ordering should align against scenes.csv.
    """
    csv_path = os.path.join(project_dir, 'reference', 'scene-briefs.csv')
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
    if 'id' not in headers:
        log(f'WARNING: scene-briefs.csv missing required column id; '
            f'have {headers}. Skipping briefs mode.')
        return []
    out: list[Brief] = []
    for i, line in enumerate(lines[1:], start=1):
        cells = line.split('|')
        if len(cells) != len(headers):
            log(f'WARNING: skipping malformed scene-briefs.csv row {i} in '
                f'{csv_path} ({len(cells)} cells, expected {len(headers)})')
            continue
        row = dict(zip(headers, cells))
        brief_id = row.get('id', '').strip()
        if not brief_id:
            log(f'WARNING: scene-briefs.csv row {i} missing id; skipping.')
            continue

        def _arr(col: str) -> tuple[str, ...]:
            cell = row.get(col, '').strip()
            if not cell:
                return ()
            return tuple(s.strip() for s in cell.split(';') if s.strip())

        engine_fields = (
            row.get('goal', '').strip(),
            row.get('conflict', '').strip(),
            row.get('outcome', '').strip(),
            row.get('crisis', '').strip(),
            row.get('decision', '').strip(),
        )
        if not any(engine_fields):
            # Migration scaffolding — empty placeholder row for a scene
            # that hasn't been briefed yet. The deterministic pre-pass
            # would otherwise emit five high-severity findings per row
            # for the entire pre-briefed corpus.
            log(f'INFO: scene-briefs.csv row {i} (id={brief_id}) has all '
                'scene-engine fields empty; treating as pre-briefed and '
                'skipping.')
            continue
        out.append(Brief(
            id=brief_id,
            goal=engine_fields[0],
            conflict=engine_fields[1],
            outcome=engine_fields[2],
            crisis=engine_fields[3],
            decision=engine_fields[4],
            knowledge_in=_arr('knowledge_in'),
            knowledge_out=_arr('knowledge_out'),
            key_actions=row.get('key_actions', '').strip(),
            key_dialogue=row.get('key_dialogue', '').strip(),
            emotions=row.get('emotions', '').strip(),
            motifs=_arr('motifs'),
            subtext=row.get('subtext', '').strip(),
            continuity_deps=_arr('continuity_deps'),
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
        scene_map_scenes = parse_scene_map(project_dir)
        briefs = parse_scene_briefs(project_dir)
        _write_strict_checklist(output_dir, artifacts, rubric,
                                  spine_events, architecture_scenes,
                                  scene_map_scenes, briefs)
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

    scene_map_scenes = parse_scene_map(project_dir)
    scene_map_extension: SceneMapExtension | None = None
    if scene_map_scenes:
        log(f'Scene map detected ({len(scene_map_scenes)} scenes) — '
            'running per-scene-map matrix + whole-map axes.')
        scene_map_extension = _run_scene_map_extension(
            project_dir, output_dir, log_dir, scene_map_scenes,
            architecture_scenes, artifacts, rubric, coaching,
        )
        if scene_map_extension['status'] != 'ok':
            status = 'partial'

    briefs = parse_scene_briefs(project_dir)
    briefs_extension: BriefsExtension | None = None
    if briefs:
        log(f'Briefs detected ({len(briefs)} briefed scenes) — running '
            'per-brief matrix + whole-briefs axes.')
        briefs_extension = _run_briefs_extension(
            project_dir, output_dir, log_dir, briefs, scene_map_scenes,
            artifacts, rubric, coaching,
        )
        if briefs_extension['status'] != 'ok':
            status = 'partial'

    return _result(
        coaching=coaching, status=status, output_dir=output_dir,
        composite=composite, scores=scores, deltas=deltas,
        diagnostic=parsed.get('diagnostic') or {},
        act_shape=act_shape_extension,
        spine=spine_extension,
        architecture=architecture_extension,
        scene_map=scene_map_extension,
        briefs=briefs_extension,
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
             scene_map: SceneMapExtension | None = None,
             briefs: BriefsExtension | None = None,
             cross_tier: CrossTierExtension | None = None,
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
        'scene_map': scene_map,
        'briefs': briefs,
        'cross_tier': cross_tier,
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
        invoke_to_file(prompt, model, log_file,
                       max_tokens=_PITCH_MAX_TOKENS)
    except Exception as e:
        log(f'ERROR: story-power LLM call failed: {e}')
        return None, 'llm_error'
    text = _read_response_text(log_file)
    parsed = _parse_response(text)
    if not parsed:
        _record_cost(project_dir, log_file, model, target='story-power:unparseable')
        log(f'ERROR: story-power LLM response unparseable; raw at '
            f'{log_file}{_truncation_hint(log_file, _PITCH_MAX_TOKENS)}')
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


# Output-token ceilings per tier. The pitch + act-shape + spine tiers
# return bounded payloads (8 axes × ≤3 acts; 5-10 events × 3 axes); 4K
# and 8K respectively are sufficient. The per-row-heavy tiers
# (architecture, scene-map, briefs) emit per-scene / per-brief
# rationales that scale with project size — at real-sized project
# counts the 8K ceiling truncates the response mid-JSON, producing
# parse failures (issue #245). 32K leaves substantial headroom over
# the observed wall and remains well under the per-model output cap
# (see api.MODEL_MAX_OUTPUT for the source of truth — Opus 4.6 caps
# at 128K, Sonnet at 64K).
_PITCH_MAX_TOKENS = 4096
_FIXED_PAYLOAD_TIER_MAX_TOKENS = 8192
_PER_ROW_TIER_MAX_TOKENS = 32768

# Monotonic ordering is an implicit design invariant: smaller payload
# ⇒ smaller budget. A typo-class swap (e.g. setting pitch to 40960
# and per-row to 4096) would currently only surface at LLM-truncation
# time on the per-row tiers; this assert catches it at import.
assert (_PITCH_MAX_TOKENS
        <= _FIXED_PAYLOAD_TIER_MAX_TOKENS
        <= _PER_ROW_TIER_MAX_TOKENS), (
    f'story-power tier ceilings must be monotone non-decreasing '
    f'(pitch={_PITCH_MAX_TOKENS}, fixed-payload={_FIXED_PAYLOAD_TIER_MAX_TOKENS}, '
    f'per-row={_PER_ROW_TIER_MAX_TOKENS})'
)


# Anthropic stop_reason values per
# https://docs.anthropic.com/en/api/messages — a closed set. The
# Literal narrows downstream comparisons statically; the companion
# frozenset gives runtime membership for schema-drift detection
# (mirrors the BriefOutcome / VALID_BRIEF_OUTCOMES pattern). The
# empty-string sentinel covers missing-from-response / unreadable
# log file (see _read_stop_reason).
StopReason = Literal[
    'end_turn',
    'max_tokens',
    'stop_sequence',
    'tool_use',
    'pause_turn',
    'refusal',
    '',
]
KNOWN_STOP_REASONS: frozenset[StopReason] = frozenset({
    'end_turn', 'max_tokens', 'stop_sequence',
    'tool_use', 'pause_turn', 'refusal', '',
})
# Module-load contract: the only stop_reason the truncation hint cares
# about must be a recognized value, otherwise the helper silently
# disables itself.
assert 'max_tokens' in KNOWN_STOP_REASONS, (
    '_truncation_hint compares against literal "max_tokens"; if that '
    'value drops out of KNOWN_STOP_REASONS, truncation detection is '
    'silently disabled'
)


def _read_stop_reason(log_file: str) -> str:
    """Read the LLM's `stop_reason` from the raw log file. Returns an
    empty string when the file is missing / unreadable / lacks the
    field / has a non-dict top-level (e.g., partial write produced a
    JSON list).

    Used to distinguish truncation (`max_tokens`) from other
    unparseable-response causes so the error message names the
    actual cause rather than just 'parse failed'.

    Logs an INFO with the unrecognized value when stop_reason is
    present but not in KNOWN_STOP_REASONS — this surfaces Anthropic
    API schema drift (a new value appearing) so the codebase doesn't
    silently lose truncation detection on a future change.

    Logs a WARNING on OSError (file should exist but couldn't be
    read) so the diagnostic itself doesn't fail silently — mirrors
    _read_response_text's behavior. A JSONDecodeError is *expected*
    on partial writes (the file exists, content is partial) and
    stays quiet.
    """
    try:
        with open(log_file, encoding='utf-8') as f:
            resp = json.load(f)
    except OSError as e:
        log(f'WARNING: could not read story-power log to extract '
            f'stop_reason: {e}')
        return ''
    except json.JSONDecodeError:
        return ''
    if not isinstance(resp, dict):
        # A non-dict top level (list / string / number) is malformed
        # for an Anthropic response shape; .get would crash and
        # propagate AttributeError through the f-string in the
        # caller, suppressing the original unparseable-error message.
        return ''
    raw = resp.get('stop_reason', '')
    if not isinstance(raw, str):
        return ''
    if raw and raw not in KNOWN_STOP_REASONS:
        log(f'INFO: story-power LLM returned unrecognized '
            f'stop_reason={raw!r}; truncation detection will not '
            'fire on this value. If Anthropic added a new stop_reason '
            'token, extend KNOWN_STOP_REASONS to match.')
    return raw


def _truncation_hint(log_file: str, max_tokens: int) -> str:
    """Return a descriptive suffix when the LLM hit `max_tokens`.

    Returns '' when stop_reason is anything else. The caller appends
    this to the unparseable ERROR so the user sees the actual cause
    without grepping the raw log.

    The wording is hedged ("likely truncated") rather than asserting
    truncation outright: stop_reason='max_tokens' guarantees the LLM
    stopped at the budget, but the response could in principle land
    on valid-but-incomplete JSON whose parse failure has a different
    proximate cause. Truncation is overwhelmingly the most likely
    explanation when both signals fire together."""
    if _read_stop_reason(log_file) != 'max_tokens':
        return ''
    return (
        f' (LLM hit max_tokens={max_tokens}; the response was likely '
        'truncated mid-JSON. The tier output scales with project '
        'size — consider reducing scope or raising the per-tier '
        'ceiling.)'
    )


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
        invoke_to_file(prompt, model, log_file,
                       max_tokens=_FIXED_PAYLOAD_TIER_MAX_TOKENS)
    except Exception as e:
        log(f'ERROR: act-shape LLM call failed: {e}. Pitch-mode scorecard '
            'still stands.')
        return _empty_extension('llm_error')
    text = _read_response_text(log_file)
    parsed = _parse_response_act_shape(text)
    if not parsed:
        _record_cost(project_dir, log_file, model,
                     target='story-power:act-shape:unparseable')
        log(f'ERROR: act-shape LLM response unparseable; raw at '
            f'{log_file}{_truncation_hint(log_file, _FIXED_PAYLOAD_TIER_MAX_TOKENS)}. '
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
                              scene_map_scenes: list[MappedScene] | None = None,
                              briefs: list[Brief] | None = None,
                              ) -> None:
    """strict coaching: rule-based checklist of signals per axis, no LLM
    call. Extends with blanks for each populated tier (act-shape,
    spine, architecture, scene-map, briefs) so strict-mode authors get
    the same coverage the LLM modes produce."""
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
    if scene_map_scenes:
        out.extend([
            '# Scene-map tier (per scene + whole-map)',
            '',
            'Two axes per scene-map row (architecture coverage, '
            'continuity coherence).',
            '',
        ])
        for s in scene_map_scenes:
            out.extend([
                f'## {s.id} — pov={s.pov or "—"} '
                f'arch={s.architecture_scene or "(interstitial)"}',
                '',
            ])
            for axis in PER_MAP_SCENE_AXES:
                out.append(f'- {axis.name}: __')
            out.append('')
        out.extend([
            '# Whole-scene-map axes',
            '',
            'Five axes scored over the scene map as a whole (see the '
            '"Scene-map mode" section of the rubric for full signals).',
            '',
        ])
        for axis in MAP_AXES:
            out.extend([
                f'## {axis.name} (weight {axis.weight})',
                '',
                f'Self-score (1-10): __',
                '',
                'Whole-scene-map signals you found:',
                '- ',
                '',
            ])
    if briefs:
        out.extend([
            '# Briefs tier (per brief + whole-briefs)',
            '',
            'Two axes per brief (scene-engine integrity, concreteness).',
            '',
        ])
        for b in briefs:
            out.extend([
                f'## {b.id} — outcome={b.outcome or "—"}',
                '',
            ])
            for axis in PER_BRIEF_AXES:
                out.append(f'- {axis.name}: __')
            out.append('')
        out.extend([
            '# Whole-briefs axes',
            '',
            'Five axes scored over the briefs corpus as a whole (see the '
            '"Briefs mode" section of the rubric for full signals).',
            '',
        ])
        for axis in BRIEFS_AXES:
            out.extend([
                f'## {axis.name} (weight {axis.weight})',
                '',
                f'Self-score (1-10): __',
                '',
                'Whole-briefs signals you found:',
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
        invoke_to_file(prompt, model, log_file,
                       max_tokens=_FIXED_PAYLOAD_TIER_MAX_TOKENS)
    except Exception as e:
        log(f'ERROR: spine LLM call failed: {e}. Pitch result still stands.')
        return _empty_spine_extension('llm_error')
    text = _read_response_text(log_file)
    parsed = _parse_response_spine(text)
    if not parsed:
        _record_cost(project_dir, log_file, model,
                     target='story-power:spine:unparseable')
        log(f'ERROR: spine LLM response unparseable; raw at '
            f'{log_file}{_truncation_hint(log_file, _FIXED_PAYLOAD_TIER_MAX_TOKENS)}.')
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
        invoke_to_file(prompt, model, log_file,
                       max_tokens=_PER_ROW_TIER_MAX_TOKENS)
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
        log(f'ERROR: architecture LLM response unparseable; raw at '
            f'{log_file}{_truncation_hint(log_file, _PER_ROW_TIER_MAX_TOKENS)}.')
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


# ---------------------------------------------------------------------------
# Scene-map extension (Layer 1 per-scene + Layer 2 whole-map)
# ---------------------------------------------------------------------------

# Conservative band — typical drafts vary 20-40% from target.
_WORD_COUNT_LOW_RATIO = 0.5
_WORD_COUNT_HIGH_RATIO = 2.0


def _empty_scene_map_extension(status: StoryPowerStatus) -> SceneMapExtension:
    """Placeholder SceneMapExtension for a failed run."""
    return {
        'per_scene_scores': {},
        'whole_scene_map_scores': {},
        'scene_map_diagnostic': {},
        'continuity_findings': [],
        'proposed_operations': [],
        'status': status,
    }


_BACKWARD_TIMELINE_ALLOWED_TYPES = frozenset({
    'flashback', 'interlude', 'prologue',
})


def _check_continuity_deterministic(scenes: list[MappedScene],
                                      architecture_ids: set[str],
                                      ) -> list[ContinuityFinding]:
    """High-confidence continuity checks on adjacent pairs + per-row
    cross-reference validation.

    When architecture_ids is empty (no architecture.csv on disk),
    the cross-reference check is skipped wholesale with one INFO log.
    Without the skip, every scene with a populated architecture_scene
    field would flag as "broken" — a noise storm that swamps the
    actionable findings.
    """
    findings: list[ContinuityFinding] = []
    check_architecture = bool(architecture_ids)
    if not check_architecture and any(s.architecture_scene for s in scenes):
        log('INFO: scene-map continuity check skipping architecture '
            'cross-reference — no reference/architecture.csv detected. '
            'Populated architecture_scene values will be re-validated '
            'once architecture.csv exists.')
    for i, scene in enumerate(scenes):
        if (check_architecture and scene.architecture_scene
                and scene.architecture_scene not in architecture_ids):
            findings.append({
                'scene_id': scene.id,
                'field': 'architecture_scene',
                'issue': (
                    f"architecture_scene={scene.architecture_scene!r} "
                    'does not match any id in reference/architecture.csv'
                ),
                'severity': 'high',
            })
        if scene.target_words > 0 and scene.word_count > 0:
            ratio = scene.word_count / scene.target_words
            if ratio < _WORD_COUNT_LOW_RATIO or ratio > _WORD_COUNT_HIGH_RATIO:
                findings.append({
                    'scene_id': scene.id,
                    'field': 'word_count',
                    'issue': (
                        f'word_count={scene.word_count} vs '
                        f'target_words={scene.target_words} '
                        f'({ratio:.1f}× — outside the '
                        f'{_WORD_COUNT_LOW_RATIO}-{_WORD_COUNT_HIGH_RATIO}× '
                        'pacing band)'
                    ),
                    'severity': 'medium',
                })
        if i == 0:
            continue
        prev = scenes[i - 1]
        try:
            curr_day = int(scene.timeline_day) if scene.timeline_day else None
            prev_day = int(prev.timeline_day) if prev.timeline_day else None
        except (TypeError, ValueError):
            curr_day = prev_day = None
        if (curr_day is not None and prev_day is not None
                and curr_day < prev_day
                and scene.scene_type.lower() not in _BACKWARD_TIMELINE_ALLOWED_TYPES):
            allowed = ', '.join(sorted(_BACKWARD_TIMELINE_ALLOWED_TYPES))
            findings.append({
                'scene_id': scene.id,
                'preceding_id': prev.id,
                'field': 'timeline_day',
                'issue': (
                    f'timeline_day went backward ({prev_day} → {curr_day}) '
                    f'but scene_type={scene.scene_type!r} '
                    f'(expected one of: {allowed})'
                ),
                'severity': 'high',
            })
    return findings


def _build_scene_map_prompt(scenes: list[MappedScene],
                              architecture_scenes: list[SceneRow],
                              artifacts: PitchArtifacts,
                              det_findings: list[ContinuityFinding],
                              rubric: str) -> str:
    """Assemble the scene-map LLM prompt. Inlines deterministic
    continuity findings as ground-truth signal."""
    per_axis_list = ', '.join(f'"{a.key}"' for a in PER_MAP_SCENE_AXES)
    map_axis_list = ', '.join(f'"{a.key}"' for a in MAP_AXES)
    scenes_block = '\n'.join(
        f'### {s.id} (seq={s.seq if s.seq is not None else "—"} pov={s.pov or "—"} '
        f'day={s.timeline_day or "—"} type={s.scene_type or "—"} '
        f'arch={s.architecture_scene or "(interstitial)"})\n'
        f'  location: {s.location or "—"}, time_of_day: {s.time_of_day or "—"}, '
        f'words: {s.word_count}/{s.target_words}\n'
        f'  summary: {s.summary}'
        for s in scenes
    )
    if architecture_scenes:
        arch_block = '\n'.join(
            f'- {a.id} ({a.title or "—"}): {a.summary[:200]}'
            for a in architecture_scenes
        )
    else:
        arch_block = '(no architecture.csv populated)'
    if det_findings:
        det_block = '\n'.join(
            f'- {f["scene_id"]}.{f["field"]} [{f["severity"]}]: {f["issue"]}'
            for f in det_findings
        )
    else:
        det_block = '(no deterministic findings — score from the LLM-only pass)'

    return f"""You are scoring the SCENE MAP of a manuscript. The scene map is the
full sequence of every scene including interstitials. Each row carries
continuity metadata (pov, location, timeline_day, time_of_day,
scene_type, word_count, architecture_scene) no upstream artifact has.
Your job:

1. Per-scene Layer 1: score each scene-map row on the two per-scene
   axes (architecture_coverage, continuity_coherence).
2. Whole-map Layer 2: score the map as a whole on the five
   whole-scene-map axes.
3. Surface continuity findings and propose SPECIFIC scene operations
   (merge / split / insert / reorder / promote) — full id lists, not
   vague rewrites.

The deterministic pre-pass already flagged the findings below — treat
these as ground-truth signal and seed continuity_coherence scoring
with them rather than re-discovering them.

# Rubric

{rubric}

# Pitch context

## Logline
{artifacts.logline}

## Synopsis
{artifacts.synopsis}

# Architecture anchors (for coverage_completeness)

{arch_block}

# Scene map under evaluation

{scenes_block}

# Deterministic continuity findings (pre-pass)

{det_block}

# Task

Valid per-scene axis keys: {per_axis_list}
Valid whole-scene-map axis keys: {map_axis_list}

Return a JSON object with this exact shape:

{{
  "per_scene": [
    {{
      "scene_id": "<scene id>",
      "scores": [
        {{"axis": "{PER_MAP_SCENE_AXES[0].key}", "score": 1-10 integer,
          "rationale": "one-sentence justification"}},
        ... one entry per per-scene axis ...
      ]
    }},
    ... one entry per scene in seq order ...
  ],
  "whole_scene_map": [
    {{"axis": "{MAP_AXES[0].key}",
      "score": 1-10 integer,
      "positive_signals": "semicolon-separated quoted signals",
      "negative_signals": "semicolon-separated quoted gaps",
      "rationale": "one-sentence justification"}},
    ... one entry per whole-scene-map axis ...
  ],
  "scene_map_diagnostic": {{
    "lowest_axis": "name of the lowest-scoring axis across both layers",
    "lowest_axis_average": "the average on that axis as a decimal",
    "summary": "one sentence: what the lowest axis tells you",
    "coverage_assessment": "one sentence: how scene-map coverage maps to architecture anchors",
    "high_leverage_move": "one sentence: ONE specific change that would lift the most ground"
  }},
  "continuity_findings": [
    {{"scene_id": "<id>", "preceding_id": "<id or empty>",
      "field": "pov|location|timeline_day|word_count|architecture_scene",
      "issue": "what's wrong",
      "severity": "high|medium|low"}}
  ],
  "proposed_operations": [
    {{"operation": "merge|split|insert|reorder|promote",
      "scene_ids": ["<id1>", "<id2>"],
      "summary": "one sentence: what the operation accomplishes",
      "rationale": "which axes this would lift, in 'axis: was → now' form"}}
  ]
}}

Reserve 10 for prose-verified excellence. Be specific and grounded —
quote the scene-map rows. The proposed operations are the most
valuable output; treat them as concrete structural moves.
Return ONLY the JSON object.
"""


def _extract_per_scene_map_scores(parsed: dict, scene_ids: list[str]
                                     ) -> dict[str, dict[str, int]]:
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
            if axis not in PER_MAP_SCENE_AXIS_BY_KEY:
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
    _log_extraction_drops('per-scene-map', drops)
    return out


def _extract_whole_scene_map_scores(parsed: dict) -> WholeSceneMapScores:
    out: WholeSceneMapScores = {}
    drops: list[str] = []
    for row in parsed.get('whole_scene_map') or []:
        if not isinstance(row, dict):
            drops.append(f'non-dict whole_scene_map row: {row!r}')
            continue
        axis = row.get('axis')
        if axis not in MAP_AXIS_BY_KEY:
            drops.append(f'unknown whole-scene-map axis={axis!r}')
            continue
        try:
            score = int(row.get('score'))
        except (TypeError, ValueError):
            drops.append(f'non-int whole-scene-map score in {axis}: '
                         f'{row.get("score")!r}')
            continue
        if not 1 <= score <= 10:
            drops.append(
                f'out-of-range whole-scene-map score in {axis}: {score}'
            )
            continue
        out[axis] = score  # type: ignore[literal-required]
    _log_extraction_drops('whole-scene-map', drops)
    return out


def _extract_continuity_findings(parsed: dict) -> list[ContinuityFinding]:
    out: list[ContinuityFinding] = []
    drops: list[str] = []
    for row in parsed.get('continuity_findings') or []:
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
        finding: ContinuityFinding = {
            'scene_id': scene_id,
            'field': field,
            'issue': issue,
            'severity': severity,
        }
        preceding_id = row.get('preceding_id', '').strip()
        if preceding_id:
            finding['preceding_id'] = preceding_id
        out.append(finding)
    _log_extraction_drops('continuity_findings', drops)
    return out


def _extract_proposed_operations(parsed: dict
                                    ) -> list[ProposedSceneOperation]:
    out: list[ProposedSceneOperation] = []
    drops: list[str] = []
    for row in parsed.get('proposed_operations') or []:
        if not isinstance(row, dict):
            drops.append(f'non-dict row: {row!r}')
            continue
        operation = row.get('operation', '').strip().lower()
        scene_ids = row.get('scene_ids', [])
        summary = row.get('summary', '').strip()
        if operation not in SCENE_OPERATIONS:
            drops.append(f'unknown operation={operation!r}')
            continue
        if not isinstance(scene_ids, list) or not scene_ids:
            drops.append(f'empty/non-list scene_ids in {operation} row')
            continue
        if not summary:
            drops.append(f'missing summary in {operation} {scene_ids}')
            continue
        cleaned_ids = [str(s).strip() for s in scene_ids
                       if str(s).strip()]
        expected = SCENE_OPERATION_ARITY[operation]
        if len(cleaned_ids) != expected:
            drops.append(
                f'{operation} requires {expected} scene_id(s); got '
                f'{len(cleaned_ids)}: {cleaned_ids}'
            )
            continue
        out.append({
            'operation': operation,  # type: ignore[typeddict-item]
            'scene_ids': cleaned_ids,
            'summary': summary,
            'rationale': row.get('rationale', '').strip(),
        })
    _log_extraction_drops('proposed_operations', drops)
    return out


def _parse_response_scene_map(text: str) -> dict | None:
    missing_fields: list[str] = []

    def _take(obj):
        if not isinstance(obj, dict):
            return None
        per_scene = obj.get('per_scene')
        whole_map = obj.get('whole_scene_map')
        local_missing = []
        if not isinstance(per_scene, list):
            local_missing.append('per_scene')
        if not isinstance(whole_map, list):
            local_missing.append('whole_scene_map')
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
        log(f'WARNING: scene-map LLM returned valid JSON but missing '
            f'required list(s): {", ".join(missing_fields)}.')
    return None


def _run_scene_map_extension(project_dir: str, output_dir: str,
                                log_dir: str,
                                scenes: list[MappedScene],
                                architecture_scenes: list[SceneRow],
                                artifacts: PitchArtifacts,
                                rubric: str,
                                coaching: CoachingLevel,
                                ) -> SceneMapExtension:
    """Run the scene-map LLM call after the deterministic continuity
    pre-pass. Pitch result still stands on any failure."""
    architecture_ids = {a.id for a in architecture_scenes}
    det_findings = _check_continuity_deterministic(scenes, architecture_ids)

    prompt = _build_scene_map_prompt(scenes, architecture_scenes, artifacts,
                                        det_findings, rubric)
    model = select_model('creative')
    log_file = os.path.join(log_dir,
                            os.path.basename(output_dir) + '-scene-map.json')
    os.makedirs(log_dir, exist_ok=True)
    try:
        invoke_to_file(prompt, model, log_file,
                       max_tokens=_PER_ROW_TIER_MAX_TOKENS)
    except Exception as e:
        log(f'ERROR: scene-map LLM call failed: {e}. Pitch result still stands.')
        ext = _empty_scene_map_extension('llm_error')
        ext['continuity_findings'] = det_findings
        return ext
    text = _read_response_text(log_file)
    parsed = _parse_response_scene_map(text)
    if not parsed:
        _record_cost(project_dir, log_file, model,
                     target='story-power:scene-map:unparseable')
        log(f'ERROR: scene-map LLM response unparseable; raw at '
            f'{log_file}{_truncation_hint(log_file, _PER_ROW_TIER_MAX_TOKENS)}.')
        ext = _empty_scene_map_extension('unparseable')
        ext['continuity_findings'] = det_findings
        return ext
    _record_cost(project_dir, log_file, model,
                 target='story-power:scene-map')

    scene_ids = [s.id for s in scenes]
    per_scene = _extract_per_scene_map_scores(parsed, scene_ids)
    whole_map = _extract_whole_scene_map_scores(parsed)
    diag = parsed.get('scene_map_diagnostic') or {}
    llm_findings = _extract_continuity_findings(parsed)
    proposed_ops = _extract_proposed_operations(parsed)
    continuity_findings = det_findings + llm_findings

    empty_scenes = [sid for sid in scene_ids if not per_scene.get(sid)]
    has_any_per_scene = any(per_scene.get(sid) for sid in scene_ids)
    has_any_whole_map = bool(whole_map)
    if empty_scenes and has_any_per_scene:
        # Write the full empty-scene id list to a sidecar so the author
        # can grep it. The previous "first 5, then ..." truncation lost
        # actionability for large scene maps (30 of 60 empty → only 5
        # named in the log, 25 lost).
        sidecar = os.path.join(output_dir, 'scene-map-empty-scenes.txt')
        _safe_write(sidecar, '\n'.join(empty_scenes) + '\n',
                    recover_hint=log_file)
        log(f'ERROR: scene-map extraction produced zero valid scores for '
            f'{len(empty_scenes)} scene(s); full list at {sidecar}; '
            f'refusing to write per-scene-map-matrix.csv with empty row(s). '
            f'Raw response: {log_file}')
    elif not has_any_per_scene:
        log(f'ERROR: scene-map extraction produced zero valid per-scene '
            f'scores; refusing to write per-scene-map-matrix.csv. '
            f'Raw response: {log_file}')
    if not has_any_whole_map:
        log(f'ERROR: scene-map extraction produced zero valid whole-map '
            f'scores; refusing to write whole-scene-map-axes.csv. '
            f'Raw response: {log_file}')

    expected_per_scene = 2 * len(scenes)
    actual_per_scene = sum(len(s) for s in per_scene.values())
    missing_per_scene = max(0, expected_per_scene - actual_per_scene)
    missing_map_axes = [a.key for a in MAP_AXES if a.key not in whole_map]
    status: StoryPowerStatus = 'ok'
    if missing_per_scene or missing_map_axes:
        status = 'partial'
        parts = []
        if missing_per_scene:
            parts.append(f'{missing_per_scene} per-scene cell(s) missing')
        if missing_map_axes:
            parts.append(
                f'{len(missing_map_axes)} whole-map axis/axes missing '
                f'({", ".join(missing_map_axes)})'
            )
        log(f'WARNING: scene-map extraction partial — {"; ".join(parts)}.')
    if status == 'ok':
        assert per_scene and whole_map, (
            'scene-map extension status=ok requires non-empty '
            'per_scene_scores and whole_scene_map_scores'
        )

    write_matrix = has_any_per_scene and not empty_scenes
    write_whole_map = has_any_whole_map
    if coaching == 'full':
        if write_matrix:
            _write_per_scene_map_matrix(output_dir, scenes, per_scene,
                                          recover_hint=log_file)
        if write_whole_map:
            _write_whole_scene_map_axes(output_dir, whole_map, parsed,
                                          recover_hint=log_file)
        if write_matrix or write_whole_map:
            _append_scene_map_diagnostic(
                output_dir, scenes, per_scene, whole_map,
                continuity_findings, proposed_ops, diag,
                include_matrix=write_matrix,
                include_whole_map=write_whole_map,
            )
    else:
        if write_matrix or write_whole_map:
            _append_scene_map_coaching_brief(
                output_dir, scenes, per_scene, whole_map,
                continuity_findings, proposed_ops, diag,
                include_matrix=write_matrix,
                include_whole_map=write_whole_map,
                recover_hint=log_file,
            )

    return {
        'status': status,
        'per_scene_scores': per_scene,
        'whole_scene_map_scores': whole_map,
        'scene_map_diagnostic': diag,
        'continuity_findings': continuity_findings,
        'proposed_operations': proposed_ops,
    }


# ---------------------------------------------------------------------------
# Scene-map writers
# ---------------------------------------------------------------------------

def _write_per_scene_map_matrix(output_dir: str, scenes: list[MappedScene],
                                   per_scene: dict[str, dict[str, int]],
                                   *, recover_hint: str = '') -> None:
    """Write per-scene-map-matrix.csv — one row per scene-map scene
    with the two per-scene axes."""
    csv_path = os.path.join(output_dir, 'per-scene-map-matrix.csv')
    headers = (['scene_id', 'pov', 'architecture_scene']
               + [a.key for a in PER_MAP_SCENE_AXES])
    lines = ['|'.join(headers)]
    for scene in scenes:
        scores = per_scene.get(scene.id, {})
        row = [scene.id, scene.pov or '',
               scene.architecture_scene or '']
        for axis in PER_MAP_SCENE_AXES:
            row.append(str(scores.get(axis.key, '')))
        lines.append('|'.join(_sanitize_cell(c) for c in row))
    _safe_write(csv_path, '\n'.join(lines) + '\n', recover_hint=recover_hint)


def _write_whole_scene_map_axes(output_dir: str,
                                   whole_map: WholeSceneMapScores,
                                   parsed: dict, *,
                                   recover_hint: str = '') -> None:
    """Write whole-scene-map-axes.csv — one row per Layer 2 axis."""
    csv_path = os.path.join(output_dir, 'whole-scene-map-axes.csv')
    headers = ['axis', 'name', 'score', 'weight', 'positive_signals',
               'negative_signals', 'rationale']
    rows_by_axis = {r.get('axis'): r for r in parsed.get('whole_scene_map', [])
                    if isinstance(r, dict)}
    lines = ['|'.join(headers)]
    for axis in MAP_AXES:
        row = rows_by_axis.get(axis.key, {})
        lines.append('|'.join(_sanitize_cell(c) for c in (
            axis.key,
            axis.name,
            str(whole_map.get(axis.key, '')),
            str(axis.weight),
            row.get('positive_signals', ''),
            row.get('negative_signals', ''),
            row.get('rationale', ''),
        )))
    _safe_write(csv_path, '\n'.join(lines) + '\n', recover_hint=recover_hint)


def _scene_map_diagnostic_section(
        scenes: list[MappedScene],
        per_scene: dict[str, dict[str, int]],
        whole_map: WholeSceneMapScores,
        continuity_findings: list[ContinuityFinding],
        proposed_ops: list[ProposedSceneOperation],
        diag: SceneMapDiagnostic, *,
        include_matrix: bool = True,
        include_whole_map: bool = True,
        ) -> list[str]:
    """Shared scene-map markdown section (full diagnostic.md + coach brief)."""
    out: list[str] = []
    if include_matrix:
        out.extend([
            '## Per-scene matrix (scene-map Layer 1)',
            '',
            '| Scene | POV | Architecture | Coverage | Continuity |',
            '|---|---|---|---|---|',
        ])
        for s in scenes:
            sc = per_scene.get(s.id, {})
            out.append(
                f'| {s.id} | {s.pov or "—"} | '
                f'{s.architecture_scene or "—"} | '
                f'{sc.get("architecture_coverage", "–")} | '
                f'{sc.get("continuity_coherence", "–")} |'
            )
    if include_whole_map:
        if out:
            out.append('')
        out.extend([
            '## Whole-scene-map axes (scene-map Layer 2)',
            '',
            '| Axis | Score | Weight |',
            '|---|---|---|',
        ])
        for axis in MAP_AXES:
            s = whole_map.get(axis.key, '–')
            out.append(f'| {axis.name} | {s} | {axis.weight} |')

    if continuity_findings:
        out.extend(['', '## Continuity findings', ''])
        for f in continuity_findings:
            ctx = (f' (after {f["preceding_id"]})'
                   if f.get('preceding_id') else '')
            out.append(
                f'- **{f["scene_id"]}**{ctx} [{f["severity"]}] '
                f'`{f["field"]}`: {f["issue"]}'
            )

    if proposed_ops:
        out.extend(['', '## Proposed scene operations', ''])
        for op in proposed_ops:
            ids = ', '.join(op['scene_ids'])
            out.extend([
                f'### {op["operation"].upper()}: {ids}',
                '',
                f'**Summary:** {op["summary"]}',
                '',
                f'**Rationale:** {op.get("rationale") or "(none provided)"}',
                '',
            ])

    out.extend([
        '',
        '## Scene-map diagnostic',
        '',
        f'**Coverage assessment:** {diag.get("coverage_assessment") or "(none provided)"}',
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


def _append_scene_map_diagnostic(
        output_dir: str, scenes: list[MappedScene],
        per_scene: dict[str, dict[str, int]],
        whole_map: WholeSceneMapScores,
        continuity_findings: list[ContinuityFinding],
        proposed_ops: list[ProposedSceneOperation],
        diag: SceneMapDiagnostic, *,
        include_matrix: bool = True,
        include_whole_map: bool = True,
        ) -> None:
    """Append the scene-map section to the existing diagnostic.md."""
    md_path = os.path.join(output_dir, 'diagnostic.md')
    if not os.path.isfile(md_path):
        log(f'WARNING: scene-map diagnostic could not be appended — '
            f'{md_path} does not exist (upstream pitch-diagnostic write '
            'likely failed). Scene-map scores were computed but their '
            'diagnostic narrative is lost.')
        return
    try:
        with open(md_path, encoding='utf-8') as f:
            existing = f.read()
    except OSError as e:
        log(f'WARNING: could not append scene-map diagnostic to {md_path}: {e}')
        return
    section = _scene_map_diagnostic_section(
        scenes, per_scene, whole_map, continuity_findings,
        proposed_ops, diag,
        include_matrix=include_matrix,
        include_whole_map=include_whole_map,
    )
    _safe_write(md_path, existing + '\n' + '\n'.join(section) + '\n')


def _append_scene_map_coaching_brief(
        output_dir: str, scenes: list[MappedScene],
        per_scene: dict[str, dict[str, int]],
        whole_map: WholeSceneMapScores,
        continuity_findings: list[ContinuityFinding],
        proposed_ops: list[ProposedSceneOperation],
        diag: SceneMapDiagnostic, *,
        include_matrix: bool = True,
        include_whole_map: bool = True,
        recover_hint: str = '',
        ) -> None:
    """coach coaching: append scene-map sections to coaching-brief.md."""
    md_path = os.path.join(output_dir, 'coaching-brief.md')
    if not os.path.isfile(md_path):
        log(f'WARNING: scene-map coaching brief could not be appended — '
            f'{md_path} does not exist (upstream coach-brief write likely '
            'failed). Scene-map scores were computed but are not captured '
            'in the brief.')
        return
    try:
        with open(md_path, encoding='utf-8') as f:
            existing = f.read()
    except OSError as e:
        log(f'WARNING: could not append scene-map coaching brief to {md_path}: {e}')
        return
    section = _scene_map_diagnostic_section(
        scenes, per_scene, whole_map, continuity_findings,
        proposed_ops, diag,
        include_matrix=include_matrix,
        include_whole_map=include_whole_map,
    )
    prelude = [
        '# Scene-map extension (LLM proposals — author confirms)',
        '',
        'Proposed scene operations are concrete structural moves, not '
        'directives — the author decides whether each merge/split/insert/'
        'reorder/promote is the right move at this stage.',
        '',
    ]
    _safe_write(md_path,
                existing + '\n' + '\n'.join(prelude + section) + '\n',
                recover_hint=recover_hint)


# ---------------------------------------------------------------------------
# Briefs extension (Layer 1 per-brief + Layer 2 whole-briefs)
# ---------------------------------------------------------------------------

# Threshold: 4+ consecutive briefs with the same outcome enum is a streak.
# Smaller windows fire on coincidence (any well-paced novel has runs of
# `yes-but` outcomes during rising action); 4 is the band where the
# repetition starts feeling monotonic.
_OUTCOME_STREAK_LEN = 4


def _empty_briefs_extension(status: StoryPowerStatus) -> BriefsExtension:
    """Placeholder BriefsExtension for a failed run."""
    return {
        'per_brief_scores': {},
        'whole_briefs_scores': {},
        'briefs_diagnostic': {},
        'brief_findings': [],
        'proposed_brief_updates': [],
        'status': status,
    }


def _check_briefs_deterministic(
        briefs: list[Brief], seq_order: list[str],
        ) -> list[BriefFinding]:
    """Five high-confidence checks the briefs pre-pass runs against the
    corpus:

    1. Missing required scene-engine field (goal/conflict/outcome/
       crisis/decision): high per missing field.
    2. Invalid outcome enum: high.
    3. Knowledge orphan: knowledge_in fact has no upstream knowledge_out
       (walking continuity_deps transitively when present, falling back
       to seq when not): medium.
    4. Outcome streak of 4+ identical outcomes (by seq when both
       briefs+scenes.csv exist, falling back to brief list order): medium
       (low when the streak is `yes-but`).
    5. Motif singleton (motif appears in exactly one brief): low.

    seq_order is the ordered list of scene ids from scenes.csv; when
    empty, brief-list order is used as the seq stand-in. The LLM seeds
    its scoring with these findings.
    """
    findings: list[BriefFinding] = []
    brief_by_id = {b.id: b for b in briefs}

    for b in briefs:
        for field_name, value in (
            ('goal', b.goal), ('conflict', b.conflict),
            ('outcome', b.outcome), ('crisis', b.crisis),
            ('decision', b.decision),
        ):
            if not value:
                findings.append({
                    'scene_id': b.id,
                    'field': field_name,
                    'issue': f'required brief field {field_name!r} is empty',
                    'severity': 'high',
                })
        if b.outcome and b.outcome not in VALID_BRIEF_OUTCOMES:
            allowed = ', '.join(sorted(VALID_BRIEF_OUTCOMES))
            findings.append({
                'scene_id': b.id,
                'field': 'outcome',
                'issue': (
                    f'outcome={b.outcome!r} not in valid set '
                    f'({allowed})'
                ),
                'severity': 'high',
            })

    # Knowledge orphans: walk continuity_deps to gather ancestor
    # knowledge_out; any knowledge_in fact not covered is an orphan.
    # Broken continuity_deps (referrer → non-existent brief id) are
    # collected separately so they surface as their own (referrer,
    # missing_target)-deduped findings instead of being silently
    # absorbed into orphan-knowledge false-positives.
    seen_missing_deps: set[tuple[str, str]] = set()
    for b in briefs:
        if not b.knowledge_in:
            # Still walk the dep graph to surface broken-dep findings —
            # a brief with no knowledge_in can still have a typo in
            # continuity_deps that downstream briefs rely on.
            for dep in b.continuity_deps:
                if dep and dep not in brief_by_id:
                    key = (b.id, dep)
                    if key not in seen_missing_deps:
                        seen_missing_deps.add(key)
                        findings.append({
                            'scene_id': b.id,
                            'field': 'continuity_deps',
                            'issue': (
                                f'continuity_deps references {dep!r} '
                                'which is not present in scene-briefs.csv'
                            ),
                            'severity': 'medium',
                        })
            continue
        # Bounded graph walk over continuity_deps (DFS via stack/pop;
        # the `visited` set bounds the walk regardless of cycle
        # topology, so triadic and deeper cycles terminate too).
        ancestor_knowledge: set[str] = set()
        ancestor_origin: dict[str, str] = {}  # fact → providing scene id
        visited: set[str] = set()
        stack = [b.id]
        while stack:
            current = stack.pop()
            if current in visited:
                continue
            visited.add(current)
            cb = brief_by_id.get(current)
            if cb is None:
                # Broken dep — surface it as its own finding (deduped
                # by referrer+target across the outer loop) so the
                # author sees the typo, not just downstream
                # orphan-knowledge false-positives the broken edge
                # produces. `current` here is the dep id that pointed
                # to nothing; the referrer is whichever brief listed
                # it (we don't track that here — the absence is
                # blamed on `b` since the orphan is in b's chain).
                key = (b.id, current)
                if key not in seen_missing_deps:
                    seen_missing_deps.add(key)
                    findings.append({
                        'scene_id': b.id,
                        'field': 'continuity_deps',
                        'issue': (
                            f'continuity_deps chain reaches {current!r} '
                            'which is not present in scene-briefs.csv'
                        ),
                        'severity': 'medium',
                    })
                continue
            if cb.id != b.id:
                # Don't credit B's own knowledge_out as covering B's
                # knowledge_in; a brief can't be its own source.
                for fact in cb.knowledge_out:
                    if fact and fact not in ancestor_origin:
                        ancestor_origin[fact] = cb.id
                        ancestor_knowledge.add(fact)
            for dep in cb.continuity_deps:
                if dep not in visited:
                    stack.append(dep)
        for fact in b.knowledge_in:
            if not fact:
                continue
            if fact not in ancestor_knowledge:
                orphan: BriefFinding = {
                    'scene_id': b.id,
                    'field': 'knowledge_in',
                    'issue': (
                        f'knowledge_in fact {fact!r} has no upstream '
                        'knowledge_out in any continuity_deps ancestor'
                    ),
                    'severity': 'medium',
                }
                # When the brief lists a direct dep, point the author
                # at it as the closest ancestor they'd expect the fact
                # to have appeared in. Orphan findings without any
                # dep at all leave preceding_id unset.
                if b.continuity_deps:
                    direct_dep = b.continuity_deps[0]
                    if direct_dep:
                        orphan['preceding_id'] = direct_dep
                findings.append(orphan)

    # Outcome streak: order briefs by scene seq when possible.
    if seq_order:
        seq_index = {sid: i for i, sid in enumerate(seq_order)}
        ordered = sorted(briefs, key=lambda b: seq_index.get(b.id, len(seq_order)))
    else:
        ordered = list(briefs)
    streak_start = 0
    while streak_start < len(ordered):
        current_outcome = ordered[streak_start].outcome
        if not current_outcome:
            streak_start += 1
            continue
        end = streak_start + 1
        while (end < len(ordered)
               and ordered[end].outcome == current_outcome):
            end += 1
        run_len = end - streak_start
        if run_len >= _OUTCOME_STREAK_LEN:
            run_ids = [ordered[i].id for i in range(streak_start, end)]
            severity: Severity = 'low' if current_outcome == 'yes-but' else 'medium'
            findings.append({
                'scene_id': run_ids[0],
                'field': 'outcome',
                'issue': (
                    f'outcome={current_outcome!r} repeats for '
                    f'{run_len} consecutive briefs ({", ".join(run_ids)})'
                ),
                'severity': severity,
            })
        streak_start = end

    # Motif singletons.
    motif_counts: dict[str, list[str]] = {}
    for b in briefs:
        for m in b.motifs:
            motif_counts.setdefault(m, []).append(b.id)
    for motif, scene_ids in motif_counts.items():
        if len(scene_ids) == 1:
            findings.append({
                'scene_id': scene_ids[0],
                'field': 'motifs',
                'issue': (
                    f'motif {motif!r} appears in only one brief — '
                    'singleton motifs miss the recurrence craft surface'
                ),
                'severity': 'low',
            })

    return findings


def _build_briefs_prompt(briefs: list[Brief],
                           scene_seq: list[str],
                           artifacts: PitchArtifacts,
                           det_findings: list[BriefFinding],
                           rubric: str) -> str:
    """Assemble the briefs LLM prompt. Inlines deterministic findings as
    ground-truth signal."""
    per_axis_list = ', '.join(f'"{a.key}"' for a in PER_BRIEF_AXES)
    briefs_axis_list = ', '.join(f'"{a.key}"' for a in BRIEFS_AXES)
    # Render briefs in seq order when possible, otherwise CSV order.
    if scene_seq:
        seq_index = {sid: i for i, sid in enumerate(scene_seq)}
        ordered = sorted(briefs,
                         key=lambda b: seq_index.get(b.id, len(scene_seq)))
    else:
        ordered = briefs

    def _arr_str(arr: tuple[str, ...]) -> str:
        return '; '.join(arr) if arr else '—'

    briefs_block = '\n\n'.join(
        f'### {b.id}\n'
        f'  goal: {b.goal or "—"}\n'
        f'  conflict: {b.conflict or "—"}\n'
        f'  outcome: {b.outcome or "—"}\n'
        f'  crisis: {b.crisis or "—"}\n'
        f'  decision: {b.decision or "—"}\n'
        f'  knowledge_in: {_arr_str(b.knowledge_in)}\n'
        f'  knowledge_out: {_arr_str(b.knowledge_out)}\n'
        f'  key_actions: {b.key_actions or "—"}\n'
        f'  key_dialogue: {b.key_dialogue or "—"}\n'
        f'  emotions: {b.emotions or "—"}\n'
        f'  motifs: {_arr_str(b.motifs)}\n'
        f'  subtext: {b.subtext or "—"}\n'
        f'  continuity_deps: {_arr_str(b.continuity_deps)}'
        for b in ordered
    )
    if det_findings:
        det_block = '\n'.join(
            f'- {f["scene_id"]}.{f["field"]} [{f["severity"]}]: {f["issue"]}'
            for f in det_findings
        )
    else:
        det_block = '(no deterministic findings — score from the LLM-only pass)'
    allowed_outcomes = ', '.join(sorted(VALID_BRIEF_OUTCOMES))

    return f"""You are scoring the BRIEFS of a manuscript. A brief is the drafting
contract for one scene: scene-engine fields (goal, conflict, outcome,
crisis, decision), information state (knowledge_in / knowledge_out),
execution beats (key_actions, key_dialogue, emotions, motifs, subtext),
and scene-graph edges (continuity_deps).

Your job:

1. Per-brief Layer 1: score each brief on the two per-brief axes
   (scene_engine_integrity, concreteness_brief).
2. Whole-briefs Layer 2: score the corpus on the five whole-briefs
   axes (outcome_distribution, knowledge_flow_continuity,
   crisis_density, subtext_presence, motif_recurrence).
3. Surface brief findings and propose SPECIFIC brief-field updates
   (full proposed_value text, not vague critique).

The deterministic pre-pass already flagged the findings below — treat
these as ground-truth signal and seed scene_engine_integrity,
knowledge_flow_continuity, and outcome_distribution scoring with them
rather than re-discovering them.

Valid outcome enum: {allowed_outcomes}.

# Rubric

{rubric}

# Pitch context

## Logline
{artifacts.logline}

## Synopsis
{artifacts.synopsis}

# Briefs under evaluation

{briefs_block}

# Deterministic brief findings (pre-pass)

{det_block}

# Task

Valid per-brief axis keys: {per_axis_list}
Valid whole-briefs axis keys: {briefs_axis_list}

Return a JSON object with this exact shape:

{{
  "per_brief": [
    {{
      "scene_id": "<brief id>",
      "scores": [
        {{"axis": "{PER_BRIEF_AXES[0].key}", "score": 1-10 integer,
          "rationale": "one-sentence justification"}},
        ... one entry per per-brief axis ...
      ]
    }},
    ... one entry per brief ...
  ],
  "whole_briefs": [
    {{"axis": "{BRIEFS_AXES[0].key}",
      "score": 1-10 integer,
      "positive_signals": "semicolon-separated quoted signals",
      "negative_signals": "semicolon-separated quoted gaps",
      "rationale": "one-sentence justification"}},
    ... one entry per whole-briefs axis ...
  ],
  "briefs_diagnostic": {{
    "lowest_axis": "name of the lowest-scoring axis across both layers",
    "lowest_axis_average": "the average on that axis as a decimal",
    "summary": "one sentence: what the lowest axis tells you",
    "scene_engine_assessment": "one sentence: how the briefs corpus encodes scene-engine integrity overall",
    "high_leverage_move": "one sentence: ONE specific change that would lift the most ground"
  }},
  "brief_findings": [
    {{"scene_id": "<id>",
      "field": "goal|conflict|outcome|crisis|decision|knowledge_in|knowledge_out|emotions|subtext|motifs|...",
      "issue": "what's wrong",
      "severity": "high|medium|low"}}
  ],
  "proposed_brief_updates": [
    {{"scene_id": "<id>",
      "field": "<brief field name>",
      "current_value": "<existing value or empty>",
      "proposed_value": "<concrete replacement text the author can drop in>",
      "rationale": "which axes this lifts, in 'axis: was → now' form"}}
  ]
}}

Reserve 10 for prose-verified excellence. Be specific and grounded —
quote the brief fields. The proposed updates are the most valuable
output; treat them as concrete drafting contracts the author can
literally paste into the CSV.
Return ONLY the JSON object.
"""


def _extract_per_brief_scores(parsed: dict, brief_ids: list[str]
                                 ) -> dict[str, dict[str, int]]:
    valid_ids = set(brief_ids)
    out: dict[str, dict[str, int]] = {bid: {} for bid in brief_ids}
    drops: list[str] = []
    for sc_row in parsed.get('per_brief') or []:
        if not isinstance(sc_row, dict):
            drops.append(f'non-dict per_brief row: {sc_row!r}')
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
            if axis not in PER_BRIEF_AXIS_BY_KEY:
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
    _log_extraction_drops('per-brief', drops)
    return out


def _extract_whole_briefs_scores(parsed: dict) -> WholeBriefsScores:
    out: WholeBriefsScores = {}
    drops: list[str] = []
    for row in parsed.get('whole_briefs') or []:
        if not isinstance(row, dict):
            drops.append(f'non-dict whole_briefs row: {row!r}')
            continue
        axis = row.get('axis')
        if axis not in BRIEFS_AXIS_BY_KEY:
            drops.append(f'unknown whole-briefs axis={axis!r}')
            continue
        try:
            score = int(row.get('score'))
        except (TypeError, ValueError):
            drops.append(f'non-int whole-briefs score in {axis}: '
                         f'{row.get("score")!r}')
            continue
        if not 1 <= score <= 10:
            drops.append(
                f'out-of-range whole-briefs score in {axis}: {score}'
            )
            continue
        out[axis] = score  # type: ignore[literal-required]
    _log_extraction_drops('whole-briefs', drops)
    return out


def _extract_brief_findings(parsed: dict) -> list[BriefFinding]:
    out: list[BriefFinding] = []
    drops: list[str] = []
    for row in parsed.get('brief_findings') or []:
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
        finding: BriefFinding = {
            'scene_id': scene_id,
            'field': field,
            'issue': issue,
            'severity': severity,
        }
        preceding_id = row.get('preceding_id', '').strip()
        if preceding_id:
            finding['preceding_id'] = preceding_id
        out.append(finding)
    _log_extraction_drops('brief_findings', drops)
    return out


def _extract_proposed_brief_updates(parsed: dict
                                       ) -> list[ProposedBriefUpdate]:
    """Pull LLM-proposed brief-field updates. Tolerant of missing
    optional fields. Drops rows missing scene_id, field, or
    proposed_value."""
    out: list[ProposedBriefUpdate] = []
    drops: list[str] = []
    for row in parsed.get('proposed_brief_updates') or []:
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
    _log_extraction_drops('proposed_brief_updates', drops)
    return out


def _parse_response_briefs(text: str) -> dict | None:
    missing_fields: list[str] = []

    def _take(obj):
        if not isinstance(obj, dict):
            return None
        per_brief = obj.get('per_brief')
        whole_briefs = obj.get('whole_briefs')
        local_missing = []
        if not isinstance(per_brief, list):
            local_missing.append('per_brief')
        if not isinstance(whole_briefs, list):
            local_missing.append('whole_briefs')
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
        log(f'WARNING: briefs LLM returned valid JSON but missing '
            f'required list(s): {", ".join(missing_fields)}.')
    return None


def _run_briefs_extension(project_dir: str, output_dir: str,
                            log_dir: str,
                            briefs: list[Brief],
                            scene_map_scenes: list[MappedScene],
                            artifacts: PitchArtifacts,
                            rubric: str,
                            coaching: CoachingLevel,
                            ) -> BriefsExtension:
    """Run the briefs LLM call after the deterministic pre-pass. Pitch
    result still stands on any failure."""
    seq_order = [s.id for s in scene_map_scenes]
    det_findings = _check_briefs_deterministic(briefs, seq_order)

    prompt = _build_briefs_prompt(briefs, seq_order, artifacts,
                                    det_findings, rubric)
    model = select_model('creative')
    log_file = os.path.join(log_dir,
                            os.path.basename(output_dir) + '-briefs.json')
    os.makedirs(log_dir, exist_ok=True)
    try:
        invoke_to_file(prompt, model, log_file,
                       max_tokens=_PER_ROW_TIER_MAX_TOKENS)
    except Exception as e:
        log(f'ERROR: briefs LLM call failed: {e}. Pitch result still stands.')
        ext = _empty_briefs_extension('llm_error')
        ext['brief_findings'] = det_findings
        return ext
    text = _read_response_text(log_file)
    parsed = _parse_response_briefs(text)
    if not parsed:
        _record_cost(project_dir, log_file, model,
                     target='story-power:briefs:unparseable')
        log(f'ERROR: briefs LLM response unparseable; raw at '
            f'{log_file}{_truncation_hint(log_file, _PER_ROW_TIER_MAX_TOKENS)}.')
        ext = _empty_briefs_extension('unparseable')
        ext['brief_findings'] = det_findings
        return ext
    _record_cost(project_dir, log_file, model,
                 target='story-power:briefs')

    brief_ids = [b.id for b in briefs]
    per_brief = _extract_per_brief_scores(parsed, brief_ids)
    whole_briefs = _extract_whole_briefs_scores(parsed)
    diag = parsed.get('briefs_diagnostic') or {}
    llm_findings = _extract_brief_findings(parsed)
    proposed_updates = _extract_proposed_brief_updates(parsed)
    brief_findings = det_findings + llm_findings

    empty_briefs = [bid for bid in brief_ids if not per_brief.get(bid)]
    has_any_per_brief = any(per_brief.get(bid) for bid in brief_ids)
    has_any_whole_briefs = bool(whole_briefs)
    if empty_briefs and has_any_per_brief:
        sidecar = os.path.join(output_dir, 'briefs-empty-scenes.txt')
        _safe_write(sidecar, '\n'.join(empty_briefs) + '\n',
                    recover_hint=log_file)
        log(f'ERROR: briefs extraction produced zero valid scores for '
            f'{len(empty_briefs)} brief(s); full list at {sidecar}; '
            f'refusing to write per-brief-matrix.csv with empty row(s). '
            f'Raw response: {log_file}')
    elif not has_any_per_brief:
        log(f'ERROR: briefs extraction produced zero valid per-brief '
            f'scores; refusing to write per-brief-matrix.csv. '
            f'Raw response: {log_file}')
    if not has_any_whole_briefs:
        log(f'ERROR: briefs extraction produced zero valid whole-briefs '
            f'scores; refusing to write whole-briefs-axes.csv. '
            f'Raw response: {log_file}')

    expected_per_brief = len(PER_BRIEF_AXES) * len(briefs)
    actual_per_brief = sum(len(s) for s in per_brief.values())
    missing_per_brief = max(0, expected_per_brief - actual_per_brief)
    missing_briefs_axes = [a.key for a in BRIEFS_AXES
                           if a.key not in whole_briefs]
    status: StoryPowerStatus = 'ok'
    if missing_per_brief or missing_briefs_axes:
        status = 'partial'
        parts = []
        if missing_per_brief:
            parts.append(f'{missing_per_brief} per-brief cell(s) missing')
        if missing_briefs_axes:
            parts.append(
                f'{len(missing_briefs_axes)} whole-briefs axis/axes missing '
                f'({", ".join(missing_briefs_axes)})'
            )
        log(f'WARNING: briefs extraction partial — {"; ".join(parts)}.')
    if status == 'ok':
        assert per_brief and whole_briefs, (
            'briefs extension status=ok requires non-empty '
            'per_brief_scores and whole_briefs_scores'
        )

    write_matrix = has_any_per_brief and not empty_briefs
    write_whole_briefs = has_any_whole_briefs
    if coaching == 'full':
        if write_matrix:
            _write_per_brief_matrix(output_dir, briefs, per_brief,
                                      recover_hint=log_file)
        if write_whole_briefs:
            _write_whole_briefs_axes(output_dir, whole_briefs, parsed,
                                      recover_hint=log_file)
        if write_matrix or write_whole_briefs:
            _append_briefs_diagnostic(
                output_dir, briefs, per_brief, whole_briefs,
                brief_findings, proposed_updates, diag,
                include_matrix=write_matrix,
                include_whole_briefs=write_whole_briefs,
            )
    else:
        if write_matrix or write_whole_briefs:
            _append_briefs_coaching_brief(
                output_dir, briefs, per_brief, whole_briefs,
                brief_findings, proposed_updates, diag,
                include_matrix=write_matrix,
                include_whole_briefs=write_whole_briefs,
                recover_hint=log_file,
            )

    return {
        'status': status,
        'per_brief_scores': per_brief,
        'whole_briefs_scores': whole_briefs,
        'briefs_diagnostic': diag,
        'brief_findings': brief_findings,
        'proposed_brief_updates': proposed_updates,
    }


# ---------------------------------------------------------------------------
# Briefs writers
# ---------------------------------------------------------------------------

def _write_per_brief_matrix(output_dir: str, briefs: list[Brief],
                              per_brief: dict[str, dict[str, int]],
                              *, recover_hint: str = '') -> None:
    """Write per-brief-matrix.csv — one row per brief with the two
    per-brief axes."""
    csv_path = os.path.join(output_dir, 'per-brief-matrix.csv')
    headers = (['scene_id', 'outcome']
               + [a.key for a in PER_BRIEF_AXES])
    lines = ['|'.join(headers)]
    for brief in briefs:
        scores = per_brief.get(brief.id, {})
        row = [brief.id, brief.outcome or '']
        for axis in PER_BRIEF_AXES:
            row.append(str(scores.get(axis.key, '')))
        lines.append('|'.join(_sanitize_cell(c) for c in row))
    _safe_write(csv_path, '\n'.join(lines) + '\n', recover_hint=recover_hint)


def _write_whole_briefs_axes(output_dir: str,
                               whole_briefs: WholeBriefsScores,
                               parsed: dict, *,
                               recover_hint: str = '') -> None:
    """Write whole-briefs-axes.csv — one row per Layer 2 axis."""
    csv_path = os.path.join(output_dir, 'whole-briefs-axes.csv')
    headers = ['axis', 'name', 'score', 'weight', 'positive_signals',
               'negative_signals', 'rationale']
    rows_by_axis = {r.get('axis'): r for r in parsed.get('whole_briefs', [])
                    if isinstance(r, dict)}
    lines = ['|'.join(headers)]
    for axis in BRIEFS_AXES:
        row = rows_by_axis.get(axis.key, {})
        lines.append('|'.join(_sanitize_cell(c) for c in (
            axis.key,
            axis.name,
            str(whole_briefs.get(axis.key, '')),
            str(axis.weight),
            row.get('positive_signals', ''),
            row.get('negative_signals', ''),
            row.get('rationale', ''),
        )))
    _safe_write(csv_path, '\n'.join(lines) + '\n', recover_hint=recover_hint)


def _briefs_diagnostic_section(
        briefs: list[Brief],
        per_brief: dict[str, dict[str, int]],
        whole_briefs: WholeBriefsScores,
        brief_findings: list[BriefFinding],
        proposed_updates: list[ProposedBriefUpdate],
        diag: BriefsDiagnostic, *,
        include_matrix: bool = True,
        include_whole_briefs: bool = True,
        ) -> list[str]:
    """Shared briefs markdown section (full diagnostic.md + coach brief)."""
    out: list[str] = []
    if include_matrix:
        out.extend([
            '## Per-brief matrix (briefs Layer 1)',
            '',
            '| Scene | Outcome | Scene-engine | Concreteness |',
            '|---|---|---|---|',
        ])
        for b in briefs:
            sc = per_brief.get(b.id, {})
            out.append(
                f'| {b.id} | {b.outcome or "—"} | '
                f'{sc.get("scene_engine_integrity", "–")} | '
                f'{sc.get("concreteness_brief", "–")} |'
            )
    if include_whole_briefs:
        if out:
            out.append('')
        out.extend([
            '## Whole-briefs axes (briefs Layer 2)',
            '',
            '| Axis | Score | Weight |',
            '|---|---|---|',
        ])
        for axis in BRIEFS_AXES:
            s = whole_briefs.get(axis.key, '–')
            out.append(f'| {axis.name} | {s} | {axis.weight} |')

    if brief_findings:
        out.extend(['', '## Brief findings', ''])
        for f in brief_findings:
            ctx = (f' (after {f["preceding_id"]})'
                   if f.get('preceding_id') else '')
            out.append(
                f'- **{f["scene_id"]}**{ctx} [{f["severity"]}] '
                f'`{f["field"]}`: {f["issue"]}'
            )

    if proposed_updates:
        out.extend(['', '## Proposed brief updates', ''])
        for u in proposed_updates:
            out.extend([
                f'### {u["scene_id"]}.{u["field"]}',
                '',
                f'**Proposed value:** {u["proposed_value"]}',
                '',
            ])
            current = u.get('current_value')
            if current:
                out.extend([f'**Current value:** {current}', ''])
            rationale = u.get('rationale')
            if rationale:
                out.extend([f'**Rationale:** {rationale}', ''])

    out.extend([
        '',
        '## Briefs diagnostic',
        '',
        f'**Scene-engine assessment:** {diag.get("scene_engine_assessment") or "(none provided)"}',
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


def _append_briefs_diagnostic(
        output_dir: str, briefs: list[Brief],
        per_brief: dict[str, dict[str, int]],
        whole_briefs: WholeBriefsScores,
        brief_findings: list[BriefFinding],
        proposed_updates: list[ProposedBriefUpdate],
        diag: BriefsDiagnostic, *,
        include_matrix: bool = True,
        include_whole_briefs: bool = True,
        ) -> None:
    """Append the briefs section to the existing diagnostic.md."""
    md_path = os.path.join(output_dir, 'diagnostic.md')
    if not os.path.isfile(md_path):
        log(f'WARNING: briefs diagnostic could not be appended — '
            f'{md_path} does not exist (upstream pitch-diagnostic write '
            'likely failed). Briefs scores were computed but their '
            'diagnostic narrative is lost.')
        return
    try:
        with open(md_path, encoding='utf-8') as f:
            existing = f.read()
    except OSError as e:
        log(f'WARNING: could not append briefs diagnostic to {md_path}: {e}')
        return
    section = _briefs_diagnostic_section(
        briefs, per_brief, whole_briefs, brief_findings,
        proposed_updates, diag,
        include_matrix=include_matrix,
        include_whole_briefs=include_whole_briefs,
    )
    _safe_write(md_path, existing + '\n' + '\n'.join(section) + '\n')


def _append_briefs_coaching_brief(
        output_dir: str, briefs: list[Brief],
        per_brief: dict[str, dict[str, int]],
        whole_briefs: WholeBriefsScores,
        brief_findings: list[BriefFinding],
        proposed_updates: list[ProposedBriefUpdate],
        diag: BriefsDiagnostic, *,
        include_matrix: bool = True,
        include_whole_briefs: bool = True,
        recover_hint: str = '',
        ) -> None:
    """coach coaching: append briefs sections to coaching-brief.md."""
    md_path = os.path.join(output_dir, 'coaching-brief.md')
    if not os.path.isfile(md_path):
        log(f'WARNING: briefs coaching brief could not be appended — '
            f'{md_path} does not exist (upstream coach-brief write likely '
            'failed). Briefs scores were computed but are not captured '
            'in the brief.')
        return
    try:
        with open(md_path, encoding='utf-8') as f:
            existing = f.read()
    except OSError as e:
        log(f'WARNING: could not append briefs coaching brief to {md_path}: {e}')
        return
    section = _briefs_diagnostic_section(
        briefs, per_brief, whole_briefs, brief_findings,
        proposed_updates, diag,
        include_matrix=include_matrix,
        include_whole_briefs=include_whole_briefs,
    )
    prelude = [
        '# Briefs extension (LLM proposals — author confirms)',
        '',
        'Proposed brief updates are concrete drafting-contract text the '
        'author can drop into the CSV, not directives — the author '
        'decides whether each proposed_value is the right move at this '
        'stage.',
        '',
    ]
    _safe_write(md_path,
                existing + '\n' + '\n'.join(prelude + section) + '\n',
                recover_hint=recover_hint)


# ---------------------------------------------------------------------------
# Cross-tier meta-diagnostic (synthesizes patterns across tier outputs)
# ---------------------------------------------------------------------------

# Tokens to ignore when tokenizing lowest_axis names — they appear in
# many tier-specific axis names but don't represent a *project-level*
# craft dimension. 'distribution', 'rhythm', 'gradient', etc. are
# axis-shape words; the meaningful tokens are concept-level
# ('concreteness', 'coherence', 'causal', 'arc', 'coverage').
_AXIS_TOKEN_STOPWORDS: frozenset[str] = frozenset({
    '', 'and', 'of', 'the', 'a', 'an',
    'distribution', 'rhythm', 'gradient', 'visibility',
    'integrity', 'depth', 'service', 'completeness',
    'resonance', 'identification', 'subversion', 'flow',
    'weight', 'shape', 'shift', 'recurrence', 'presence',
    'density', 'balance', 'rotation', 'economy', 'pacing',
})

# Tiers below this threshold count toward the project-disposition
# pattern. Picked to match the rubric's "7-8: strong; specific gaps"
# band — anything below 7 is "present but inert" or weaker.
_TIER_WEAK_THRESHOLD = 7.0

# Minimum number of weak tiers to fire the project-disposition
# pattern. At 4-of-6, the project's overall structural-craft
# strength is the actionable signal, not any single tier.
_PROJECT_DISPOSITION_THRESHOLD = 4


def _tokenize_axis_name(axis_name: str) -> set[str]:
    """Split an axis name into lowercase concept tokens for cross-tier
    matching. Drops stop-words + numeric tokens."""
    parts = re.split(r'[_\s\-]+', axis_name.lower())
    return {
        p for p in parts
        if p and p not in _AXIS_TOKEN_STOPWORDS and not p.isdigit()
    }


def _gather_tier_lowest_axes(result: StoryPowerResult) -> dict[str, str]:
    """Collect each tier's `lowest_axis` (when present + ok-ish).

    Keys are tier names ('pitch', 'act_shape', 'spine', 'architecture',
    'scene_map', 'briefs'); values are the axis names. Tiers without
    a populated lowest_axis are omitted.
    """
    out: dict[str, str] = {}
    diag = result.get('diagnostic') or {}
    pitch_lowest = (diag or {}).get('lowest_axis') if isinstance(diag, dict) else None
    if isinstance(pitch_lowest, str) and pitch_lowest:
        out['pitch'] = pitch_lowest

    for tier_key, diag_key in (
        ('act_shape', 'structural_diagnostic'),
        ('spine', 'spine_diagnostic'),
        ('architecture', 'architecture_diagnostic'),
        ('scene_map', 'scene_map_diagnostic'),
        ('briefs', 'briefs_diagnostic'),
    ):
        ext = result.get(tier_key)  # type: ignore[misc]
        if not ext:
            continue
        tier_diag = ext.get(diag_key) or {}
        lowest = tier_diag.get('lowest_axis') if isinstance(tier_diag, dict) else None
        if isinstance(lowest, str) and lowest:
            out[tier_key] = lowest
    return out


def _detect_lowest_axis_recurrence(
        lowest_axes: dict[str, str],
        ) -> list[CrossTierPattern]:
    """Find concept tokens shared by ≥2 tiers' lowest_axis names."""
    if len(lowest_axes) < 2:
        return []
    token_tiers: dict[str, list[tuple[str, str]]] = {}
    for tier, axis in lowest_axes.items():
        for token in _tokenize_axis_name(axis):
            token_tiers.setdefault(token, []).append((tier, axis))
    out: list[CrossTierPattern] = []
    for token, entries in sorted(token_tiers.items()):
        if len(entries) < 2:
            continue
        tiers_seen = {t for t, _ in entries}
        if len(tiers_seen) < 2:
            continue
        severity: Severity = 'high' if len(tiers_seen) >= 3 else 'medium'
        out.append({
            'pattern': 'lowest_axis_recurrence',
            'description': (
                f'token {token!r} appears in the lowest_axis of '
                f'{len(tiers_seen)} tiers '
                f'({", ".join(sorted(tiers_seen))}): '
                + '; '.join(f'{t}:{a}' for t, a in entries)
            ),
            'severity': severity,
            'affected_tiers': sorted(tiers_seen),
            'affected_ids': sorted({axis for _, axis in entries}),
        })
    return out


def _gather_proposal_scene_ids(
        result: StoryPowerResult,
        ) -> dict[str, set[str]]:
    """Collect each tier's scene-id proposal targets."""
    out: dict[str, set[str]] = {}
    arch = result.get('architecture')
    if arch:
        arch_ids: set[str] = set()
        for u in arch.get('proposed_field_updates') or []:
            sid = (u or {}).get('scene_id', '').strip()
            if sid:
                arch_ids.add(sid)
        for ins in arch.get('proposed_scene_insertions') or []:
            sid = (ins or {}).get('insert_after', '').strip()
            if sid:
                arch_ids.add(sid)
        if arch_ids:
            out['architecture'] = arch_ids
    sm = result.get('scene_map')
    if sm:
        sm_ids: set[str] = set()
        for op in sm.get('proposed_operations') or []:
            for sid in (op or {}).get('scene_ids') or []:
                sid = str(sid).strip()
                if sid:
                    sm_ids.add(sid)
        if sm_ids:
            out['scene_map'] = sm_ids
    br = result.get('briefs')
    if br:
        br_ids: set[str] = set()
        for u in br.get('proposed_brief_updates') or []:
            sid = (u or {}).get('scene_id', '').strip()
            if sid:
                br_ids.add(sid)
        if br_ids:
            out['briefs'] = br_ids
    return out


def _detect_scene_id_overlap(
        proposal_ids: dict[str, set[str]],
        ) -> list[CrossTierPattern]:
    """Find scene_ids targeted by proposals in ≥2 tiers."""
    if len(proposal_ids) < 2:
        return []
    by_id: dict[str, set[str]] = {}
    for tier, ids in proposal_ids.items():
        for sid in ids:
            by_id.setdefault(sid, set()).add(tier)
    out: list[CrossTierPattern] = []
    for sid in sorted(by_id):
        tiers = by_id[sid]
        if len(tiers) < 2:
            continue
        severity: Severity = 'high' if len(tiers) >= 3 else 'medium'
        out.append({
            'pattern': 'scene_id_overlap',
            'description': (
                f'scene {sid!r} is targeted by proposed fixes in '
                f'{len(tiers)} tiers ({", ".join(sorted(tiers))}) — '
                'a multi-tier leverage point'
            ),
            'severity': severity,
            'affected_tiers': sorted(tiers),
            'affected_ids': [sid],
        })
    return out


def _gather_finding_scene_ids(
        result: StoryPowerResult,
        ) -> dict[str, set[str]]:
    """Collect each tier's finding-list scene_ids."""
    out: dict[str, set[str]] = {}
    arch = result.get('architecture')
    if arch:
        arch_ids = {
            (f or {}).get('scene_id', '').strip()
            for f in arch.get('field_findings') or []
        }
        arch_ids.discard('')
        if arch_ids:
            out['architecture'] = arch_ids
    sm = result.get('scene_map')
    if sm:
        sm_ids = {
            (f or {}).get('scene_id', '').strip()
            for f in sm.get('continuity_findings') or []
        }
        sm_ids.discard('')
        if sm_ids:
            out['scene_map'] = sm_ids
    br = result.get('briefs')
    if br:
        br_ids = {
            (f or {}).get('scene_id', '').strip()
            for f in br.get('brief_findings') or []
        }
        br_ids.discard('')
        if br_ids:
            out['briefs'] = br_ids
    return out


def _detect_field_coherence_cascade(
        finding_ids: dict[str, set[str]],
        ) -> list[CrossTierPattern]:
    """Find scene_ids flagged in ≥2 tiers' finding lists."""
    if len(finding_ids) < 2:
        return []
    by_id: dict[str, set[str]] = {}
    for tier, ids in finding_ids.items():
        for sid in ids:
            by_id.setdefault(sid, set()).add(tier)
    out: list[CrossTierPattern] = []
    for sid in sorted(by_id):
        tiers = by_id[sid]
        if len(tiers) < 2:
            continue
        severity: Severity = 'high' if len(tiers) >= 3 else 'medium'
        out.append({
            'pattern': 'field_coherence_cascade',
            'description': (
                f'scene {sid!r} carries findings in {len(tiers)} tiers '
                f'({", ".join(sorted(tiers))}) — fix the upstream '
                "tier's row to resolve the downstream symptoms"
            ),
            'severity': severity,
            'affected_tiers': sorted(tiers),
            'affected_ids': [sid],
        })
    return out


def _tier_composite_average(scores: dict[str, int] | None) -> float | None:
    """Return the unweighted average of a tier's whole-axis scores, or
    None when nothing is present."""
    if not scores:
        return None
    vals = [v for v in scores.values() if isinstance(v, int)]
    if not vals:
        return None
    return sum(vals) / len(vals)


def _gather_tier_strengths(result: StoryPowerResult) -> dict[str, float]:
    """Collect each tier's representative strength score (composite
    for pitch, unweighted axis average for the others)."""
    out: dict[str, float] = {}
    pitch_composite = result.get('composite')
    if isinstance(pitch_composite, (int, float)) and pitch_composite > 0:
        out['pitch'] = float(pitch_composite)
    for tier_key, scores_key in (
        ('act_shape', 'structural_axis_scores'),
        ('spine', 'whole_spine_scores'),
        ('architecture', 'whole_architecture_scores'),
        ('scene_map', 'whole_scene_map_scores'),
        ('briefs', 'whole_briefs_scores'),
    ):
        ext = result.get(tier_key)  # type: ignore[misc]
        if not ext:
            continue
        avg = _tier_composite_average(ext.get(scores_key))
        if avg is not None:
            out[tier_key] = avg
    return out


def _detect_project_disposition(
        tier_strengths: dict[str, float],
        ) -> list[CrossTierPattern]:
    """Fire when ≥4 tiers score below the weak threshold."""
    weak = [
        (tier, score) for tier, score in tier_strengths.items()
        if score < _TIER_WEAK_THRESHOLD
    ]
    if len(weak) < _PROJECT_DISPOSITION_THRESHOLD:
        return []
    return [{
        'pattern': 'project_disposition',
        'description': (
            f'{len(weak)} of {len(tier_strengths)} tiers score below '
            f'{_TIER_WEAK_THRESHOLD} on their representative strength '
            f'({", ".join(f"{t}={s:.1f}" for t, s in weak)}). '
            "The project's structural-craft layer is underweight "
            'overall — consider returning to elaboration before '
            'continuing to drafting.'
        ),
        'severity': 'high',
        'affected_tiers': sorted(t for t, _ in weak),
        'affected_ids': [],
    }]


def _check_cross_tier_deterministic(
        result: StoryPowerResult,
        ) -> list[CrossTierPattern]:
    """Run the four deterministic detectors against the in-memory
    tier outputs. Each detector is independent and emits zero or more
    patterns; the full list is returned to the LLM as ground-truth
    signal."""
    findings: list[CrossTierPattern] = []
    findings.extend(_detect_lowest_axis_recurrence(
        _gather_tier_lowest_axes(result),
    ))
    findings.extend(_detect_scene_id_overlap(
        _gather_proposal_scene_ids(result),
    ))
    findings.extend(_detect_field_coherence_cascade(
        _gather_finding_scene_ids(result),
    ))
    findings.extend(_detect_project_disposition(
        _gather_tier_strengths(result),
    ))
    return findings


def _count_present_tiers(result: StoryPowerResult) -> int:
    """Count how many tier outputs are available for synthesis.

    Pitch counts when composite > 0 (pitch produced output). Each
    extension counts when present in the result — status doesn't
    have to be 'ok' since 'partial' extensions still carry data the
    LLM can synthesize.
    """
    count = 0
    if isinstance(result.get('composite'), (int, float)) and result['composite'] > 0:
        count += 1
    for tier_key in ('act_shape', 'spine', 'architecture',
                      'scene_map', 'briefs'):
        if result.get(tier_key) is not None:  # type: ignore[misc]
            count += 1
    return count
