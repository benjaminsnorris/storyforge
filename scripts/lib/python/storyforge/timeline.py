"""Timeline day assignment parsing and prompt building.

Replaces the data-heavy functions from scripts/storyforge-timeline:
  - Phase 1: Parse DELTA/EVIDENCE/ANCHOR indicators from Claude responses
  - Phase 2: Parse TIMELINE: CSV blocks with timeline_day assignments
  - Prompt building for both phases
  - CSV update for writing timeline_day values

Called from bash via:
    python3 -m storyforge.timeline parse-indicators <response_file> <scene_id>
    python3 -m storyforge.timeline parse-assignments <response_file>
    python3 -m storyforge.timeline apply <assignments_json> <metadata_csv>
"""

import json
import os
import re
import sys

from .enrich import update_csv_field


# Valid delta values for Phase 1 indicator parsing
VALID_DELTAS = frozenset({
    'same_moment', 'same_day', 'next_day',
    'days_later', 'weeks_later', 'unknown',
})


# ---------------------------------------------------------------------------
# Phase 1: Temporal Indicator Parsing
# ---------------------------------------------------------------------------

def parse_indicators(response: str, scene_id: str) -> dict:
    """Parse Claude's Phase 1 response to extract temporal indicators.

    The response contains labeled lines like::

        DELTA: next_day
        EVIDENCE: "The sun rose over the archive"
        ANCHOR: none

    Args:
        response: Raw text from Claude's Phase 1 extraction response.
        scene_id: Scene identifier (used for error context, not parsed).

    Returns:
        Dict with keys ``delta``, ``evidence``, ``anchor``.
        Delta is normalised to one of the valid values or ``unknown``.
        Evidence and anchor preserve their original text (including quotes).
    """
    delta = 'unknown'
    evidence = 'none'
    anchor = 'none'

    if not response:
        return {'delta': delta, 'evidence': evidence, 'anchor': anchor}

    for line in response.splitlines():
        stripped = line.strip()

        # DELTA
        match = re.match(r'^DELTA:\s*(.+)', stripped, re.IGNORECASE)
        if match:
            raw = match.group(1).strip().lower()
            delta = raw if raw in VALID_DELTAS else 'unknown'
            continue

        # EVIDENCE
        match = re.match(r'^EVIDENCE:\s*(.+)', stripped, re.IGNORECASE)
        if match:
            evidence = match.group(1).strip()
            continue

        # ANCHOR
        match = re.match(r'^ANCHOR:\s*(.+)', stripped, re.IGNORECASE)
        if match:
            anchor = match.group(1).strip()
            continue

    return {'delta': delta, 'evidence': evidence, 'anchor': anchor}


# ---------------------------------------------------------------------------
# Phase 1: Prompt Building
# ---------------------------------------------------------------------------

def build_phase1_prompt(scene_id: str, scene_text: str,
                        prev_scene_summary: dict | None = None) -> str:
    """Build the Phase 1 temporal extraction prompt for a single scene.

    Args:
        scene_id: The scene identifier.
        scene_text: Full prose content of the scene.
        prev_scene_summary: Optional dict with keys ``title``,
            ``time_of_day`` describing the previous scene. If *None* or
            empty, the scene is treated as the first in the sequence.

    Returns:
        The complete prompt string, or empty string if *scene_text* is
        empty/blank.
    """
    if not scene_text or not scene_text.strip():
        return ''

    if prev_scene_summary:
        prev_title = prev_scene_summary.get('title', 'untitled')
        prev_tod = prev_scene_summary.get('time_of_day', 'unknown')
    else:
        prev_title = '(first scene)'
        prev_tod = 'unknown'

    scene_title = prev_scene_summary.get('scene_title', 'untitled') if prev_scene_summary else 'untitled'
    scene_pov = prev_scene_summary.get('scene_pov', 'unknown') if prev_scene_summary else 'unknown'
    scene_tod = prev_scene_summary.get('scene_tod', 'unknown') if prev_scene_summary else 'unknown'

    return (
        'You are analyzing the temporal relationship between two consecutive '
        'scenes in a novel. Read the current scene\'s prose and answer three '
        'questions.\n'
        '\n'
        '## Previous Scene\n'
        f'Title: {prev_title}\n'
        f'Time of day: {prev_tod}\n'
        '\n'
        '## Current Scene\n'
        f'Title: {scene_title}\n'
        f'POV: {scene_pov}\n'
        f'Time of day: {scene_tod}\n'
        '\n'
        '## Scene Prose\n'
        f'{scene_text}\n'
        '\n'
        '## Questions — answer ALL three on separate labeled lines\n'
        '\n'
        'DELTA: How much time has passed between the previous scene and this '
        'one? Choose exactly one: same_moment / same_day / next_day / '
        'days_later / weeks_later / unknown\n'
        'EVIDENCE: Quote the single strongest piece of textual evidence for '
        'your answer (the exact words from the prose that most clearly '
        'establish when this scene happens relative to the previous one). '
        'If no evidence, write "none".\n'
        'ANCHOR: Is there an absolute time reference in this scene (a '
        'specific day of week, date, month, season, or named event that pins '
        'this to a calendar)? If yes, quote it. If no, write "none".'
    )


# ---------------------------------------------------------------------------
# Phase 2: Timeline Assignment Parsing
# ---------------------------------------------------------------------------

def parse_timeline_assignments(response: str) -> dict[str, int]:
    """Parse Claude's Phase 2 response to extract timeline_day assignments.

    Looks for a ``TIMELINE:`` marker followed by pipe-delimited CSV lines::

        TIMELINE:
        id|timeline_day
        scene-1|1
        scene-2|1
        scene-3|2

    Parsing is robust: non-CSV lines are skipped, the header row
    ``id|timeline_day`` is skipped, and only rows where the second field is
    a positive integer are accepted.

    Args:
        response: Raw text from Claude's Phase 2 response.

    Returns:
        Dict mapping scene_id to timeline_day (int).
    """
    assignments: dict[str, int] = {}

    if not response:
        return assignments

    in_block = False
    for line in response.splitlines():
        stripped = line.strip()

        if stripped == 'TIMELINE:':
            in_block = True
            continue

        if not in_block:
            continue

        # Skip the header row
        if stripped == 'id|timeline_day':
            continue

        # Blank line — skip but stay in block
        if not stripped:
            continue

        # A line that looks like a new section header (has colon, no pipe)
        # signals end of the CSV block
        if ':' in stripped and '|' not in stripped:
            break

        # Attempt to parse as id|day
        if '|' not in stripped:
            continue

        parts = stripped.split('|', 1)
        if len(parts) != 2:
            continue

        scene_id = parts[0].strip()
        day_str = parts[1].strip()

        if not scene_id:
            continue

        try:
            day_val = int(day_str)
        except ValueError:
            continue

        if day_val > 0:
            assignments[scene_id] = day_val

    return assignments


# ---------------------------------------------------------------------------
# Phase 2: Prompt Building
# ---------------------------------------------------------------------------

def build_phase2_prompt(scene_summaries: list[dict],
                        project_title: str) -> str:
    """Build the Phase 2 timeline assignment prompt.

    Args:
        scene_summaries: List of dicts, each with keys:
            ``id``, ``title``, ``seq``, ``time_of_day``,
            ``existing_day`` (str or empty), ``delta``, ``evidence``,
            ``anchor``.  Ordered by narrative sequence.
        project_title: Title of the novel project.

    Returns:
        The complete Phase 2 prompt string.
    """
    summary_lines = []
    scene_ids = []

    for s in scene_summaries:
        sid = s['id']
        scene_ids.append(sid)
        seq = s.get('seq', '?')
        title = s.get('title', 'untitled')
        tod = s.get('time_of_day', 'unknown')
        existing = s.get('existing_day', 'unset') or 'unset'
        delta = s.get('delta', 'unknown')
        evidence = s.get('evidence', 'none')
        anchor = s.get('anchor', 'none')

        summary_lines.append(
            f'SEQ {seq}: {title} ({sid})\n'
            f'  Time of day: {tod}\n'
            f'  Existing timeline_day: {existing}\n'
            f'  DELTA: {delta} | EVIDENCE: {evidence} | ANCHOR: {anchor}'
        )

    summaries_text = '\n\n'.join(summary_lines)

    example_rows = '\n'.join(f'{sid}|<day>' for sid in scene_ids)

    return (
        'You are assigning timeline_day values to scenes in a novel. '
        'Day 1 is the first day of the story.\n'
        '\n'
        'Each scene below includes a temporal analysis from a prior pass:\n'
        '- **DELTA**: estimated time gap from the previous scene '
        '(same_moment, same_day, next_day, days_later, weeks_later, '
        'unknown)\n'
        '- **EVIDENCE**: the strongest textual evidence for the delta\n'
        '- **ANCHOR**: any absolute time reference (day of week, date, '
        'month, season)\n'
        '\n'
        'Use the deltas to build a cumulative day count. Where the delta '
        'is "unknown", use narrative logic, time_of_day, and surrounding '
        'context to make your best judgment. Anchors should pin the '
        'timeline \u2014 if scene 30 says "Friday" and scene 28 was assigned '
        'to a Wednesday, adjust.\n'
        '\n'
        'Scenes can share a day. Days can be skipped. If a scene already '
        'has a timeline_day value, keep it unless the evidence clearly '
        'contradicts it.\n'
        '\n'
        f'## Scenes (in narrative order)\n'
        '\n'
        f'{summaries_text}\n'
        '\n'
        '## Instructions\n'
        '\n'
        'Assign a timeline_day (positive integer) to every scene. '
        'Output ONLY a pipe-delimited CSV block:\n'
        '\n'
        'TIMELINE:\n'
        f'id|timeline_day\n'
        f'{example_rows}'
    )


# ---------------------------------------------------------------------------
# CSV Update
# ---------------------------------------------------------------------------

def apply_timeline_days(assignments: dict[str, int],
                        metadata_csv: str) -> int:
    """Write timeline_day values to scene-metadata.csv.

    Args:
        assignments: Mapping of scene_id to timeline_day (int).
        metadata_csv: Path to the pipe-delimited scene-metadata.csv file.

    Returns:
        Number of scenes successfully updated.
    """
    updated = 0
    for scene_id, day_val in assignments.items():
        if update_csv_field(metadata_csv, scene_id, 'timeline_day',
                            str(day_val)):
            updated += 1
    return updated


# ---------------------------------------------------------------------------
# CLI interface
# ---------------------------------------------------------------------------

def main():
    """CLI entry point.

    Usage::

        python3 -m storyforge.timeline parse-indicators <response_file> <scene_id>
        python3 -m storyforge.timeline parse-assignments <response_file>
        python3 -m storyforge.timeline apply <assignments_json> <metadata_csv>
    """
    if len(sys.argv) < 2:
        print(
            'Usage: python3 -m storyforge.timeline <command> [args]',
            file=sys.stderr,
        )
        sys.exit(1)

    command = sys.argv[1]

    if command == 'parse-indicators':
        if len(sys.argv) < 4:
            print(
                'Usage: parse-indicators <response_file> <scene_id>',
                file=sys.stderr,
            )
            sys.exit(1)

        response_file = sys.argv[2]
        scene_id = sys.argv[3]

        with open(response_file) as f:
            response = f.read()

        result = parse_indicators(response, scene_id)
        print(json.dumps(result))

    elif command == 'parse-assignments':
        if len(sys.argv) < 3:
            print(
                'Usage: parse-assignments <response_file>',
                file=sys.stderr,
            )
            sys.exit(1)

        response_file = sys.argv[2]

        with open(response_file) as f:
            response = f.read()

        result = parse_timeline_assignments(response)
        print(json.dumps(result))

    elif command == 'apply':
        if len(sys.argv) < 4:
            print(
                'Usage: apply <assignments_json> <metadata_csv>',
                file=sys.stderr,
            )
            sys.exit(1)

        assignments_json = sys.argv[2]
        metadata_csv = sys.argv[3]

        # Accept either a file path or inline JSON
        if os.path.isfile(assignments_json):
            with open(assignments_json) as f:
                raw = json.load(f)
        else:
            raw = json.loads(assignments_json)

        # Convert string keys/values from JSON back to str->int
        assignments = {str(k): int(v) for k, v in raw.items()}

        updated = apply_timeline_days(assignments, metadata_csv)
        print(f'{updated}')

    else:
        print(f'Unknown command: {command}', file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
