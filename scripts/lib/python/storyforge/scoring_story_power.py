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
    CoachingLevel, get_plugin_dir, log, parse_story_summary, select_model,
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


class StoryPowerResult(TypedDict):
    """Result of score_story_power. Coaching is the requested level; status
    is the outcome. Output_dir is the timestamped directory written to
    (empty string when no directory was allocated).

    act_shape is None for pitch-only runs (no `## Act-shape` populated,
    or act-shape LLM failed before producing usable data); when set, the
    ActShapeExtension carries per-act + structural payloads.
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
        _write_strict_checklist(output_dir, artifacts, rubric)
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

    # Pitch-only is a valid result; the act-shape extension is additive,
    # not a replacement. A failed extension never overwrites the pitch
    # scorecard.
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

    return _result(
        coaching=coaching, status=status, output_dir=output_dir,
        composite=composite, scores=scores, deltas=deltas,
        diagnostic=parsed.get('diagnostic') or {},
        act_shape=act_shape_extension,
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
                              rubric: str) -> None:
    """strict coaching: rule-based checklist of signals per axis, no LLM
    call. Lists what to look for and a 'self-score 1-10' line the author
    fills in by hand.

    Extends with per-act blanks and structural-axis blanks when the
    act-shape section is populated (so strict-mode authors get the same
    coverage the LLM modes produce automatically).
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
