"""Scoring functions for the craft-weights evaluation system.

Replaces scripts/lib/scoring.sh — provides score parsing, CSV merging,
weighted-text generation, diagnosis, and proposal generation.
"""

import math
import os
import re
import shutil
import sys


# Narrative principles scored at novel level, not per scene
NARRATIVE_PRINCIPLES = {
    'campbells_monomyth', 'three_act', 'save_the_cat', 'truby_22',
    'harmon_circle', 'kishotenketsu', 'freytag',
}

# Score files and their scale labels
SCORE_FILES = [
    ('scene-scores.csv', 'scene'),
    ('act-scores.csv', 'act'),
    ('character-scores.csv', 'character'),
    ('genre-scores.csv', 'genre'),
    ('fidelity-scores.csv', 'fidelity'),
]


# ============================================================================
# CSV helpers (pipe-delimited)
# ============================================================================

def _read_csv(path: str) -> tuple[list[str], list[list[str]]]:
    """Read a pipe-delimited CSV. Returns (header_fields, data_rows).

    Strips ``\\r`` so CRLF line endings and stray carriage returns embedded
    by awk-based CSV edits never propagate into field values.
    """
    with open(path, newline='', encoding='utf-8') as f:
        raw = f.read().replace('\r\n', '\n').replace('\r', '')
    lines = [line for line in raw.splitlines() if line.strip()]
    if not lines:
        return [], []
    header = lines[0].split('|')
    rows = [line.split('|') for line in lines[1:]]
    return header, rows


def _write_csv(path: str, header: list[str], rows: list[list[str]]):
    """Write a pipe-delimited CSV."""
    with open(path, 'w') as f:
        f.write('|'.join(header) + '\n')
        for row in rows:
            f.write('|'.join(row) + '\n')


# ============================================================================
# parse_score_output
# ============================================================================

def parse_score_output(
    text: str,
    score_marker: str = 'SCORES',
    rationale_marker: str = 'RATIONALE',
) -> tuple[str, str]:
    """Extract CSV blocks from Claude output text.

    Supports two marker styles:
        1. Block markers: {{SCORES:}} ... {{END_SCORES}}
        2. Line markers: SCORES: (block ends at blank line or next UPPERCASE: marker)

    Args:
        text: The full text content from Claude's response.
        score_marker: Marker name for scores block (default 'SCORES').
        rationale_marker: Marker name for rationale block (default 'RATIONALE').

    Returns:
        Tuple of (scores_csv_text, rationale_csv_text). Either may be empty.
    """
    scores = _extract_block(text, score_marker)
    rationale = _extract_block(text, rationale_marker)
    return scores, rationale


def _extract_block(text: str, marker: str) -> str:
    """Extract a single marker block from text."""
    # Try block markers first: {{MARKER:}} ... {{END_MARKER}}
    block_pattern = re.compile(
        r'\{\{' + re.escape(marker) + r':?\}\}\s*\n(.*?)\n\s*\{\{END_' + re.escape(marker) + r'\}\}',
        re.DOTALL,
    )
    m = block_pattern.search(text)
    if m:
        return m.group(1).strip()

    # Fall back to line-based markers: MARKER: (content until blank line or next UPPERCASE:)
    lines = text.splitlines()
    found = False
    collected = []
    marker_re = re.compile(r'^' + re.escape(marker) + r':\s*$')

    for line in lines:
        if marker_re.match(line):
            found = True
            continue
        if found:
            stripped = line.strip()
            if not stripped:
                break
            # Stop at next top-level marker (e.g. RATIONALE:)
            if re.match(r'^[A-Z_]+:\s*$', line):
                break
            collected.append(line)

    return '\n'.join(collected)


# ============================================================================
# merge_score_files
# ============================================================================

def merge_score_files(target_path: str, source_path: str):
    """Merge two pipe-delimited CSVs.

    If target doesn't exist, copy source. If both exist with matching headers,
    append rows from source. If headers differ, join on the id column (first column).

    Args:
        target_path: Destination CSV file path.
        source_path: Source CSV file path to merge in.
    """
    if not os.path.isfile(source_path):
        print(f'WARNING: merge source not found: {source_path}', file=sys.stderr)
        return

    if not os.path.isfile(target_path):
        shutil.copy2(source_path, target_path)
        return

    t_header, t_rows = _read_csv(target_path)
    s_header, s_rows = _read_csv(source_path)

    # Same headers: append rows
    if t_header == s_header:
        with open(target_path, 'a') as f:
            for row in s_rows:
                f.write('|'.join(row) + '\n')
        return

    # Different headers: join on id column (column 0)
    # Build lookup of target rows by id, preserving order
    t_index: dict[str, list[str]] = {}
    t_order: list[str] = []
    for row in t_rows:
        rid = row[0] if row else ''
        t_index[rid] = row
        t_order.append(rid)

    # Source columns beyond id
    s_extra_cols = s_header[1:]
    s_index: dict[str, list[str]] = {}
    for row in s_rows:
        rid = row[0] if row else ''
        s_index[rid] = row[1:] if len(row) > 1 else []
        # Track new IDs not in target
        if rid not in t_index:
            t_order.append(rid)
            t_index[rid] = [rid] + [''] * (len(t_header) - 1)

    # Merged header
    merged_header = t_header + s_extra_cols

    # Merged rows
    empty_source = [''] * len(s_extra_cols)
    merged_rows = []
    for rid in t_order:
        base = t_index[rid]
        extra = s_index.get(rid, empty_source)
        # Pad extra if shorter than expected
        while len(extra) < len(s_extra_cols):
            extra.append('')
        merged_rows.append(base + extra)

    _write_csv(target_path, merged_header, merged_rows)


# ============================================================================
# build_weighted_text
# ============================================================================

def build_weighted_text(weights_file: str, exclude_section: str = '') -> str:
    """Build markdown text listing high-priority craft principles.

    Reads craft-weights.csv, filters to effective weight >= 7, optionally
    excludes an entire section. Returns formatted text for prompt injection.

    Args:
        weights_file: Path to craft-weights.csv.
        exclude_section: Section name to exclude (e.g. 'narrative').

    Returns:
        Formatted markdown string.
    """
    if not os.path.isfile(weights_file):
        return 'No craft weights available.'

    header, rows = _read_csv(weights_file)
    # Expect columns: section|principle|weight|author_weight|notes
    col_idx = {name: i for i, name in enumerate(header)}

    high_priority = []
    for row in rows:
        section = row[col_idx.get('section', 0)] if 'section' in col_idx else ''
        principle = row[col_idx.get('principle', 1)] if 'principle' in col_idx else ''
        weight = row[col_idx.get('weight', 2)] if 'weight' in col_idx else ''
        author_weight = row[col_idx.get('author_weight', 3)] if 'author_weight' in col_idx else ''

        if exclude_section and section == exclude_section:
            continue

        eff_w = author_weight if author_weight else weight
        try:
            if int(eff_w) >= 7:
                high_priority.append(f'- **{principle}** (weight: {eff_w})')
        except (ValueError, TypeError):
            continue

    if high_priority:
        return 'Pay particular attention to these high-priority principles:\n' + '\n'.join(high_priority)
    return 'All principles are weighted equally. No high-priority overrides.'


# ============================================================================
# get_effective_weight
# ============================================================================

def get_effective_weight(weights_file: str, principle: str) -> int:
    """Return author_weight if set, else weight for a principle.

    Args:
        weights_file: Path to craft-weights.csv.
        principle: Principle name to look up.

    Returns:
        Effective weight as an integer, or 5 as default.
    """
    header, rows = _read_csv(weights_file)
    col_idx = {name: i for i, name in enumerate(header)}
    p_col = col_idx.get('principle', 1)
    w_col = col_idx.get('weight', 2)
    aw_col = col_idx.get('author_weight', 3)

    for row in rows:
        if len(row) > p_col and row[p_col] == principle:
            author_w = row[aw_col] if len(row) > aw_col else ''
            weight = row[w_col] if len(row) > w_col else ''
            val = author_w if author_w else weight
            try:
                return int(val)
            except (ValueError, TypeError):
                return 5
    return 5


# ============================================================================
# generate_diagnosis
# ============================================================================

def _power_mean(values: list[float], p: float = 0.5) -> float:
    """Compute the power mean (generalized mean) of values.

    Power mean with p=0.5 penalizes low scores harder than arithmetic mean.
    Formula: (sum(x^p) / n) ^ (1/p)
    """
    if not values:
        return 0.0
    n = len(values)
    pow_sum = sum(v ** p for v in values)
    return (pow_sum / n) ** (1.0 / p)


def _infer_project_dir(scores_dir: str) -> str:
    """Infer project root from scores dir (typically project_dir/working/scores/cycle-N)."""
    path = os.path.normpath(os.path.abspath(scores_dir))
    parts = path.split(os.sep)
    for i, part in enumerate(parts):
        if part == 'working' and i > 0:
            return os.sep.join(parts[:i])
    return ''


def _attribute_root_causes(diag_rows, diag_header, project_dir):
    """Update root_cause column based on stall history and brief quality. Modifies in place."""
    root_cause_idx = diag_header.index('root_cause')
    worst_items_idx = diag_header.index('worst_items')
    principle_idx = diag_header.index('principle')
    priority_idx = diag_header.index('priority')

    ref_dir = os.path.join(project_dir, 'reference')
    brief_issue_scenes = None

    for row in diag_rows:
        priority = row[priority_idx]
        if priority not in ('high', 'medium'):
            continue

        principle = row[principle_idx]
        worst = row[worst_items_idx]
        if not worst:
            continue

        scene_ids = [s.strip() for s in worst.split(';') if s.strip()]

        # Check brief quality (lazy load)
        if brief_issue_scenes is None:
            try:
                from storyforge.elaborate import _read_csv_as_map
                from storyforge.hone import detect_brief_issues
                briefs = _read_csv_as_map(os.path.join(ref_dir, 'scene-briefs.csv'))
                scenes = _read_csv_as_map(os.path.join(ref_dir, 'scenes.csv'))
                intent = _read_csv_as_map(os.path.join(ref_dir, 'scene-intent.csv'))
                issues = detect_brief_issues(briefs, scenes, intent_map=intent)
                brief_issue_scenes = {i['scene_id'] for i in issues}
            except Exception:
                brief_issue_scenes = set()

        # Check stall history (lazy load per principle)
        stalled_scenes = set()
        try:
            from storyforge.history import detect_stalls
            stalls = detect_stalls(project_dir, principle)
            stalled_scenes = {s['scene_id'] for s in stalls}
        except Exception:
            pass

        # Attribution: any worst-item scene with brief issues or stalls → brief
        for sid in scene_ids:
            if sid in brief_issue_scenes or sid in stalled_scenes:
                row[root_cause_idx] = 'brief'
                break


def generate_diagnosis(scores_dir: str, prev_dir: str, weights_file: str):
    """Analyze score CSVs, compute averages, identify worst items, write diagnosis.csv.

    Processes scene-scores.csv, act-scores.csv, character-scores.csv, and
    genre-scores.csv. For each principle column, computes power-mean average,
    finds worst items, computes delta from previous cycle, and assigns priority.

    Args:
        scores_dir: Directory containing current cycle score CSVs.
        prev_dir: Directory containing previous cycle score CSVs (may be empty string).
        weights_file: Path to craft-weights.csv.
    """
    diagnosis_file = os.path.join(scores_dir, 'diagnosis.csv')
    diag_header = ['principle', 'scale', 'avg_score', 'worst_items', 'delta_from_last', 'priority', 'root_cause']
    diag_rows: list[list[str]] = []

    for csv_name, scale in SCORE_FILES:
        score_file = os.path.join(scores_dir, csv_name)
        if not os.path.isfile(score_file):
            continue

        header, rows = _read_csv(score_file)
        if not header or not rows:
            continue

        prev_header: list[str] = []
        prev_rows: list[list[str]] = []
        if prev_dir:
            prev_file = os.path.join(prev_dir, csv_name)
            if os.path.isfile(prev_file):
                prev_header, prev_rows = _read_csv(prev_file)

        # Process each principle column (skip column 0 which is id)
        for col_idx in range(1, len(header)):
            principle = header[col_idx]
            if not principle:
                continue

            # Skip narrative principles in scene-level scores
            if scale == 'scene' and principle in NARRATIVE_PRINCIPLES:
                continue

            # Collect (id, score) pairs
            id_scores: list[tuple[str, float]] = []
            for row in rows:
                if col_idx < len(row):
                    try:
                        val = float(row[col_idx])
                    except (ValueError, TypeError):
                        continue
                    id_scores.append((row[0], val))

            if not id_scores:
                continue

            scores_only = [s for _, s in id_scores]
            avg_score = _power_mean(scores_only)

            # Find worst items: below average, take up to 5
            below_avg = [(rid, s) for rid, s in id_scores if s < avg_score]
            below_avg.sort(key=lambda x: x[1])
            worst_items = ';'.join(rid for rid, _ in below_avg[:5])

            # Compute delta from previous cycle
            delta = ''
            if prev_header and prev_rows:
                # Find matching column in previous scores
                if principle in prev_header:
                    prev_col = prev_header.index(principle)
                    prev_vals = []
                    for prow in prev_rows:
                        if prev_col < len(prow):
                            try:
                                prev_vals.append(float(prow[prev_col]))
                            except (ValueError, TypeError):
                                continue
                    if prev_vals:
                        prev_avg = sum(prev_vals) / len(prev_vals)
                        d = avg_score - prev_avg
                        delta = f'+{d:.1f}' if d >= 0 else f'{d:.1f}'

            # Determine priority
            priority = 'low'
            eff_weight = 5
            if os.path.isfile(weights_file):
                eff_weight = get_effective_weight(weights_file, principle)

            is_high = avg_score < 2.0
            is_medium = avg_score < 3.0

            # Check regression > 0.25
            is_regressing = False
            if delta:
                try:
                    is_regressing = float(delta) < -0.25
                except ValueError:
                    pass

            if is_high or is_regressing:
                priority = 'high'
            elif is_medium:
                priority = 'medium'

            # Boost priority if high weight
            if eff_weight >= 9:
                if priority != 'high':
                    priority = 'high'
            elif eff_weight >= 7:
                if is_medium:
                    priority = 'high'

            diag_rows.append([
                principle, scale, f'{avg_score:.1f}', worst_items, delta, priority, 'craft',
            ])

    project_dir = _infer_project_dir(scores_dir)
    if project_dir:
        _attribute_root_causes(diag_rows, diag_header, project_dir)

    _write_csv(diagnosis_file, diag_header, diag_rows)


# ============================================================================
# generate_proposals
# ============================================================================

def generate_proposals(scores_dir: str, weights_file: str):
    """Generate improvement proposals from diagnosis.csv.

    Reads diagnosis, generates weight-bump or voice-guide proposals for
    high/medium priority principles. Also generates scene-level intent
    proposals for worst-scoring scenes.

    Args:
        scores_dir: Directory containing diagnosis.csv and score CSVs.
        weights_file: Path to craft-weights.csv.
    """
    diagnosis_file = os.path.join(scores_dir, 'diagnosis.csv')
    proposals_file = os.path.join(scores_dir, 'proposals.csv')

    if not os.path.isfile(diagnosis_file):
        return

    d_header, d_rows = _read_csv(diagnosis_file)
    col = {name: i for i, name in enumerate(d_header)}

    p_header = ['id', 'principle', 'lever', 'target', 'change', 'rationale', 'status']
    p_rows: list[list[str]] = []
    proposal_num = 0

    # Load scene-scores for scene-level proposals
    scene_scores_file = os.path.join(scores_dir, 'scene-scores.csv')
    scene_header: list[str] = []
    scene_rows: list[list[str]] = []
    if os.path.isfile(scene_scores_file):
        scene_header, scene_rows = _read_csv(scene_scores_file)

    for drow in d_rows:
        principle = drow[col.get('principle', 0)]
        scale = drow[col.get('scale', 1)]
        avg_score = drow[col.get('avg_score', 2)]
        worst_items = drow[col.get('worst_items', 3)]
        delta = drow[col.get('delta_from_last', 4)]
        priority = drow[col.get('priority', 5)]

        if priority not in ('high', 'medium'):
            continue

        # Look up current weight
        current_weight = 5
        if os.path.isfile(weights_file):
            header, rows = _read_csv(weights_file)
            w_col_idx = {name: i for i, name in enumerate(header)}
            p_idx = w_col_idx.get('principle', 1)
            wt_idx = w_col_idx.get('weight', 2)
            for row in rows:
                if len(row) > p_idx and row[p_idx] == principle:
                    try:
                        current_weight = int(row[wt_idx]) if len(row) > wt_idx and row[wt_idx] else 5
                    except ValueError:
                        current_weight = 5
                    break

        increase = 2 if priority == 'high' else 1
        new_weight = min(current_weight + increase, 10)

        proposal_num += 1
        pid = f'p{proposal_num:03d}'

        if current_weight >= 8:
            p_rows.append([
                pid, principle, 'voice_guide', 'global',
                f'add voice guidance for {principle}',
                f'avg_score {avg_score}, weight already {current_weight}',
                'pending',
            ])
        else:
            p_rows.append([
                pid, principle, 'craft_weight', 'global',
                f'weight {current_weight} → {new_weight}',
                f'avg_score {avg_score}, priority {priority}',
                'pending',
            ])

        # Scene-level proposals for worst items
        if worst_items and scene_header:
            scene_col = scene_header.index(principle) if principle in scene_header else -1
            if scene_col >= 0:
                for scene_id in worst_items.split(';'):
                    if not scene_id:
                        continue
                    # Find this scene's score
                    scene_val = None
                    for srow in scene_rows:
                        if srow and srow[0] == scene_id and scene_col < len(srow):
                            try:
                                scene_val = int(srow[scene_col])
                            except (ValueError, TypeError):
                                break
                            break
                    if scene_val is not None and scene_val < 3:
                        proposal_num += 1
                        pid = f'p{proposal_num:03d}'
                        p_rows.append([
                            pid, principle, 'scene_intent', scene_id,
                            f'strengthen {principle} intent',
                            f'scene scores {scene_val}, needs targeted fix',
                            'pending',
                        ])

    _write_csv(proposals_file, p_header, p_rows)


# ============================================================================
# parse_scene_evaluation — pivot single-pass scores into columnar CSVs
# ============================================================================

def _extract_scores_block(text: str) -> str:
    """Extract the SCORES: block from evaluation text.

    Tries two strategies:
      1. A ``SCORES:`` header line followed by data rows until a blank line
         or another ``UPPERCASE:`` marker.
      2. A line starting with ``principle|`` (direct CSV without header marker).
    """
    lines = text.splitlines()

    # Strategy 1: SCORES: marker
    found = False
    collected: list[str] = []
    for line in lines:
        if line.strip() == 'SCORES:' or line.strip().startswith('SCORES:'):
            if line.strip() == 'SCORES:':
                found = True
                continue
        if found:
            stripped = line.strip()
            if not stripped:
                break
            if re.match(r'^[A-Z_]+:\s*$', line):
                break
            collected.append(line)

    if collected:
        return '\n'.join(collected)

    # Strategy 2: principle| header directly
    found = False
    collected = []
    for line in lines:
        if line.startswith('principle|'):
            found = True
        if found:
            stripped = line.strip()
            if not stripped:
                break
            collected.append(line)

    return '\n'.join(collected)


def parse_scene_evaluation(
    text: str,
    scene_id: str,
    diagnostics_csv: str = '',
) -> tuple[str, str]:
    """Parse a single-pass scene evaluation into pivoted score/rationale CSVs.

    Input format (per row): ``principle|score|deficits|evidence_lines``
    Output: two CSV strings with principles as columns and the scene as a row.

    If *diagnostics_csv* is provided, the canonical principle order is read
    from its ``principle`` column (unique, in file order). Otherwise, the
    model's output order is used.

    Args:
        text: Full text content from Claude's response.
        scene_id: Scene identifier for the id column.
        diagnostics_csv: Optional path to diagnostics.csv for canonical ordering.

    Returns:
        Tuple of (scores_csv, rationale_csv). Either may be empty if parsing
        fails.
    """
    scores_block = _extract_scores_block(text)
    if not scores_block:
        return '', ''

    # Parse rows into a lookup dict: principle -> (score, rationale)
    lookup: dict[str, tuple[str, str]] = {}
    for line in scores_block.splitlines():
        parts = line.split('|')
        if len(parts) < 2:
            continue
        principle = parts[0].strip()
        if principle == 'principle' or not principle:
            continue
        score = parts[1].strip() if len(parts) > 1 else ''
        deficits = parts[2].strip() if len(parts) > 2 else ''
        evidence = '|'.join(parts[3:]).strip() if len(parts) > 3 else ''

        if deficits == 'none' or not deficits:
            rationale = 'No deficits'
        else:
            deficits_clean = deficits.replace('|', '-')
            evidence_clean = evidence.replace('|', '-')
            rationale = f'{deficits_clean} ({evidence_clean})'

        lookup[principle] = (score, rationale)

    if not lookup:
        return '', ''

    # Build canonical principle list
    canonical: list[str] = []
    if diagnostics_csv and os.path.isfile(diagnostics_csv):
        header, rows = _read_csv(diagnostics_csv)
        if header:
            try:
                p_idx = header.index('principle')
            except ValueError:
                p_idx = 1  # fallback to second column
            seen: set[str] = set()
            for row in rows:
                if len(row) > p_idx:
                    p = row[p_idx]
                    if p and p not in seen:
                        seen.add(p)
                        canonical.append(p)

    # Fall back to model output order if no canonical list
    if not canonical:
        canonical = list(lookup.keys())

    # Build pivoted CSVs
    header_parts = ['id']
    score_parts = [scene_id]
    rationale_parts = [scene_id]

    for principle in canonical:
        header_parts.append(principle)
        if principle in lookup:
            s, r = lookup[principle]
            score_parts.append(s)
            rationale_parts.append(r)
        else:
            score_parts.append('')
            rationale_parts.append('')

    header_line = '|'.join(header_parts)
    scores_csv = header_line + '\n' + '|'.join(score_parts)
    rationale_csv = header_line + '\n' + '|'.join(rationale_parts)

    return scores_csv, rationale_csv


# ============================================================================
# init_craft_weights
# ============================================================================

def init_craft_weights(project_dir: str, plugin_dir: str):
    """Copy default craft-weights.csv to project if it doesn't exist.

    Args:
        project_dir: Path to the novel project root.
        plugin_dir: Path to the storyforge plugin directory.
    """
    weights_file = os.path.join(project_dir, 'working', 'craft-weights.csv')
    defaults = os.path.join(plugin_dir, 'references', 'default-craft-weights.csv')
    if not os.path.isfile(weights_file):
        os.makedirs(os.path.dirname(weights_file), exist_ok=True)
        shutil.copy2(defaults, weights_file)


# ============================================================================
# extract_rubric_section
# ============================================================================

def extract_rubric_section(section_name: str, plugin_dir: str) -> str:
    """Extract a section from scoring-rubrics.md by heading name.

    Looks for ``## section_name`` and extracts everything until the
    next ``## `` heading.

    Args:
        section_name: The heading text to match (e.g. "Narrative Frameworks").
        plugin_dir: Path to the storyforge plugin directory.

    Returns:
        The section content, or empty string if not found.
    """
    rubric_file = os.path.join(plugin_dir, 'references', 'scoring-rubrics.md')
    if not os.path.isfile(rubric_file):
        return ''

    with open(rubric_file) as f:
        content = f.read()

    # Match ## section_name through next ## or end
    pattern = rf'^## {re.escape(section_name)}\s*\n(.*?)(?=^## |\Z)'
    m = re.search(pattern, content, re.MULTILINE | re.DOTALL)
    if m:
        return m.group(1).rstrip()
    return ''


# ============================================================================
# build_principle_guide
# ============================================================================

def _build_principle_guide(principle_name: str, guide_file: str) -> str:
    """Extract the guide section for a specific principle.

    The guide uses ``### principle_name`` headers. Extracts everything
    between the matching header and the next ``###`` or ``##`` header.

    Args:
        principle_name: The principle name to match.
        guide_file: Path to the principle-guide.md file.

    Returns:
        The guide content, or empty string if not found.
    """
    if not os.path.isfile(guide_file):
        return ''

    with open(guide_file) as f:
        content = f.read()

    pattern = rf'^### {re.escape(principle_name)}\s*\n(.*?)(?=^###? |\Z)'
    m = re.search(pattern, content, re.MULTILINE | re.DOTALL)
    if m:
        return m.group(1).rstrip()
    return ''


# ============================================================================
# build_evaluation_criteria
# ============================================================================

def build_evaluation_criteria(diagnostics_csv: str, guide_file: str) -> str:
    """Build combined evaluation criteria from diagnostics CSV and principle guide.

    For each principle found in the diagnostics CSV, produces a section with:
    - A diagnostic checklist (the questions from the CSV)
    - The principle guide content (what it looks like / doesn't look like)

    Args:
        diagnostics_csv: Path to the diagnostics CSV file (pipe-delimited).
        guide_file: Path to the principle-guide.md file.

    Returns:
        Formatted markdown text with evaluation criteria per principle.
    """
    if not os.path.isfile(diagnostics_csv) or not os.path.isfile(guide_file):
        return ''

    header, rows = _read_csv(diagnostics_csv)
    if not header or not rows:
        return ''

    # Locate columns by name
    col = {name: i for i, name in enumerate(header)}
    principle_idx = col.get('principle', 1)
    question_idx = col.get('question', 3)

    # Group questions by principle, preserving order
    from collections import OrderedDict
    principles: OrderedDict[str, list[str]] = OrderedDict()
    for row in rows:
        principle = row[principle_idx] if len(row) > principle_idx else ''
        question = row[question_idx] if len(row) > question_idx else ''
        if not principle:
            continue
        if principle not in principles:
            principles[principle] = []
        if question:
            principles[principle].append(question)

    # Build output
    parts = []
    for principle, questions in principles.items():
        parts.append('---')
        parts.append('')
        parts.append(f'### {principle}')
        parts.append('')
        parts.append('**Diagnostic checklist:**')
        for q in questions:
            parts.append(f'- {q}')

        guide = _build_principle_guide(principle, guide_file)
        if guide:
            parts.append('')
            parts.append(guide)
        parts.append('')

    return '\n'.join(parts)


# ============================================================================
# Exemplar collection
# ============================================================================

def collect_exemplars(scores_dir: str, project_dir: str, cycle: str):
    """Collect high-scoring scenes (5/5) into the exemplar bank."""
    exemplars_file = os.path.join(project_dir, 'working', 'exemplars.csv')
    scores_file = os.path.join(scores_dir, 'scene-scores.csv')

    if not os.path.isfile(scores_file):
        return

    if not os.path.isfile(exemplars_file):
        os.makedirs(os.path.dirname(exemplars_file), exist_ok=True)
        with open(exemplars_file, 'w') as f:
            f.write('principle|scene_id|score|excerpt|cycle\n')

    # Read existing exemplars to avoid duplicates
    existing = set()
    with open(exemplars_file) as f:
        for line in f:
            if line.startswith('principle|'):
                continue
            parts = line.strip().split('|')
            if len(parts) >= 2:
                existing.add((parts[0], parts[1]))

    header, rows = _read_csv(scores_file)
    rationale_file = os.path.join(scores_dir, 'scene-rationale.csv')
    rat_header, rat_rows = ([], [])
    if os.path.isfile(rationale_file):
        rat_header, rat_rows = _read_csv(rationale_file)

    # Build rationale lookup: {(scene_id, principle): text}
    rat_lookup = {}
    if rat_header and rat_rows:
        for row in rat_rows:
            scene_id = row[0] if row else ''
            for ci, col in enumerate(rat_header):
                if ci == 0:
                    continue
                if ci < len(row) and row[ci]:
                    rat_lookup[(scene_id, col)] = row[ci]

    new_rows = []
    for row in rows:
        scene_id = row[0] if row else ''
        for ci, principle in enumerate(header):
            if ci == 0:
                continue
            if ci >= len(row) or not row[ci]:
                continue
            try:
                score_val = int(row[ci])
            except ValueError:
                continue
            if score_val >= 5 and (principle, scene_id) not in existing:
                excerpt = rat_lookup.get((scene_id, principle), 'high-scoring passage')
                excerpt = excerpt.replace('|', '-')
                new_rows.append(f'{principle}|{scene_id}|{score_val}|{excerpt}|{cycle}')

    if new_rows:
        with open(exemplars_file, 'a') as f:
            for r in new_rows:
                f.write(r + '\n')


# ============================================================================
# Validated patterns
# ============================================================================

def check_validated_patterns(project_dir: str) -> str:
    """Find tuning patterns validated across 3+ cycles. Returns pipe-delimited lines."""
    tuning_file = os.path.join(project_dir, 'working', 'tuning.csv')
    if not os.path.isfile(tuning_file):
        return ''

    counts: dict[str, int] = {}
    improvements: dict[str, float] = {}

    with open(tuning_file) as f:
        for line in f:
            if line.startswith('cycle') or line.startswith('#'):
                continue
            parts = line.strip().split('|')
            if len(parts) < 8 or parts[7] != 'true':
                continue
            key = f'{parts[2]}|{parts[3]}'
            counts[key] = counts.get(key, 0) + 1
            try:
                improvements[key] = improvements.get(key, 0.0) + (float(parts[6]) - float(parts[5]))
            except (ValueError, IndexError):
                pass

    results = []
    for key, count in counts.items():
        if count >= 3:
            avg_imp = improvements.get(key, 0.0) / count
            results.append(f'{key}|{avg_imp:.1f}')
    return '\n'.join(results)


# ============================================================================
# Score report generation
# ============================================================================

def _score_icon(score: int) -> str:
    if score >= 4:
        return '\U0001f7e2'  # green circle
    elif score >= 3:
        return '\U0001f7e1'  # yellow circle
    else:
        return '\U0001f534'  # red circle


def _sc_class(val: str) -> str:
    """Return CSS class for a score value."""
    try:
        n = int(val)
    except (ValueError, TypeError):
        return ''
    if 1 <= n <= 5:
        return f'sc-{n}'
    return ''


def generate_score_report(cycle_dir: str, project_dir: str, cycle: str,
                          mode: str, scene_count: int, cost: str):
    """Generate an HTML scoring report."""
    import subprocess
    report_file = os.path.join(cycle_dir, 'report.html')

    # Read project title
    project_title = 'Unknown'
    yaml_file = os.path.join(project_dir, 'storyforge.yaml')
    if os.path.isfile(yaml_file):
        with open(yaml_file) as f:
            for line in f:
                m = re.match(r'\s*title:\s*(.+)', line)
                if m:
                    project_title = m.group(1).strip().strip('"').strip("'")
                    break

    # Character arcs table
    char_rows = ''
    char_file = os.path.join(cycle_dir, 'character-scores.csv')
    if os.path.isfile(char_file):
        header, rows = _read_csv(char_file)
        for row in rows:
            if not row or row[0] == 'character':
                continue
            vals = [(float(row[i]) if i < len(row) and row[i] else 0) for i in range(1, 5)]
            avg = sum(vals) / max(len(vals), 1)
            cells = ''.join(f'<td class="{_sc_class(row[i] if i < len(row) else "")}">{row[i] if i < len(row) else ""}</td>'
                           for i in range(1, 5))
            char_rows += f'<tr><td>{row[0]}</td>{cells}<td><strong>{avg:.1f}</strong></td></tr>\n'

    # Act structure table
    act_rows = ''
    act_file = os.path.join(cycle_dir, 'act-scores.csv')
    if os.path.isfile(act_file):
        header, rows = _read_csv(act_file)
        for row in rows:
            if not row or row[0] == 'id':
                continue
            label = row[0].replace('act-', 'Part ')
            cells = ''.join(f'<td class="{_sc_class(row[i] if i < len(row) else "")}">{row[i] if i < len(row) else ""}</td>'
                           for i in range(1, len(header)))
            act_rows += f'<tr><td>{label}</td>{cells}</tr>\n'

    # Genre row
    genre_row = ''
    genre_file = os.path.join(cycle_dir, 'genre-scores.csv')
    if os.path.isfile(genre_file):
        header, rows = _read_csv(genre_file)
        if rows:
            row = rows[0]
            genre_row = ''.join(f'<td class="{_sc_class(row[i] if i < len(row) else "")}">{row[i] if i < len(row) else ""}</td>'
                               for i in range(len(row)))

    # Strengths / weaknesses from diagnosis
    strengths = ''
    weaknesses = ''
    diag_file = os.path.join(cycle_dir, 'diagnosis.csv')
    if os.path.isfile(diag_file):
        header, rows = _read_csv(diag_file)
        scored = []
        for row in rows:
            if len(row) >= 4:
                try:
                    avg = float(row[2]) if row[2] else 0
                except ValueError:
                    avg = 0
                if avg > 0:
                    scored.append((avg, row[0].replace('_', ' '), row[3] if len(row) > 3 else ''))
        scored.sort(key=lambda x: x[0], reverse=True)
        for avg, prin, scenes in scored[:5]:
            strengths += f'<tr><td>{prin}</td><td>{avg}</td><td>{scenes}</td></tr>\n'
        scored.sort(key=lambda x: x[0])
        for avg, prin, scenes in scored[:5]:
            weaknesses += f'<tr><td>{prin}</td><td>{avg}</td><td>{scenes}</td></tr>\n'

    # Proposals table
    proposal_rows = ''
    proposals_file = os.path.join(cycle_dir, 'proposals.csv')
    if os.path.isfile(proposals_file):
        header, rows = _read_csv(proposals_file)
        for row in rows:
            if not row or row[0] == 'id':
                continue
            prin = row[1].replace('_', ' ') if len(row) > 1 else ''
            lever = row[2].replace('_', ' ') if len(row) > 2 else ''
            change = row[4] if len(row) > 4 else ''
            rationale = row[5] if len(row) > 5 else ''
            status = row[6] if len(row) > 6 else 'pending'
            badge_cls = {'applied': 'badge-applied', 'approved': 'badge-approved',
                        'rejected': 'badge-rejected'}.get(status, 'badge-pending')
            proposal_rows += (f'<tr><td>{prin}</td><td>{lever}</td><td>{change}</td>'
                            f'<td>{rationale}</td><td><span class="badge {badge_cls}">{status}</span></td></tr>\n')

    # Scene heatmap
    scene_heatmap = ''
    scene_file = os.path.join(cycle_dir, 'scene-scores.csv')
    if os.path.isfile(scene_file):
        header, rows = _read_csv(scene_file)
        for row in rows:
            if not row or row[0] == 'id':
                continue
            vals = []
            for i in range(1, len(row)):
                try:
                    v = float(row[i])
                    if v > 0:
                        vals.append(v)
                except (ValueError, IndexError):
                    pass
            avg = _power_mean(vals) if vals else 0
            scene_heatmap += f'<tr><td>{row[0]}</td><td class="{_sc_class(str(round(avg)))}">{avg:.1f}</td></tr>\n'

    from datetime import datetime
    now = datetime.now().strftime('%Y-%m-%d %H:%M')

    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Scoring Report</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
:root {{
    --bg: #faf8f6; --surface: #fff; --border: #e5e1db; --text: #2c2420;
    --text-dim: #8a7d73; --teal: #0f766e; --teal-dim: rgba(15,118,110,0.07);
    --red: #dc2626; --amber: #d97706; --green: #16a34a;
}}
@media (prefers-color-scheme: dark) {{
    :root {{
        --bg: #1a1614; --surface: #262019; --border: rgba(255,255,255,0.08);
        --text: #ede5dd; --text-dim: #a69889; --teal: #2dd4bf; --teal-dim: rgba(45,212,191,0.08);
        --red: #f87171; --amber: #fbbf24; --green: #4ade80;
    }}
}}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: var(--bg); color: var(--text); line-height: 1.6; }}
.page {{ max-width: 960px; margin: 0 auto; padding: 40px 24px; }}
h1 {{ font-size: 28px; font-weight: 700; margin-bottom: 4px; }}
h2 {{ font-size: 18px; font-weight: 600; margin: 32px 0 12px; color: var(--teal); border-bottom: 2px solid var(--teal-dim); padding-bottom: 6px; }}
.meta {{ font-size: 13px; color: var(--text-dim); margin-bottom: 24px; }}
.meta span {{ margin-right: 16px; }}
table {{ width: 100%; border-collapse: collapse; margin-bottom: 24px; font-size: 13px; }}
th {{ text-align: left; padding: 8px 10px; background: var(--surface); border: 1px solid var(--border); font-weight: 600; font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; color: var(--text-dim); }}
td {{ padding: 6px 10px; border: 1px solid var(--border); }}
.sc-1 {{ background: rgba(220,38,38,0.15); color: var(--red); font-weight: 600; }}
.sc-2 {{ background: rgba(217,119,6,0.12); color: var(--amber); font-weight: 600; }}
.sc-3 {{ background: rgba(217,119,6,0.06); }}
.sc-4 {{ background: rgba(22,163,74,0.08); }}
.sc-5 {{ background: rgba(22,163,74,0.15); color: var(--green); font-weight: 600; }}
.badge {{ display: inline-block; padding: 1px 8px; border-radius: 10px; font-size: 11px; font-weight: 500; }}
.badge-applied {{ background: rgba(22,163,74,0.12); color: var(--green); }}
.badge-approved {{ background: rgba(22,163,74,0.06); color: var(--green); }}
.badge-rejected {{ background: rgba(220,38,38,0.08); color: var(--red); }}
.badge-pending {{ background: rgba(217,119,6,0.08); color: var(--amber); }}
.two-col {{ display: grid; grid-template-columns: 1fr 1fr; gap: 24px; }}
@media (max-width: 640px) {{ .two-col {{ grid-template-columns: 1fr; }} }}
</style>
</head>
<body>
<div class="page">
<h1>{project_title} &mdash; Scoring Report</h1>
<div class="meta">
    <span>Cycle {cycle}</span>
    <span>Mode: {mode}</span>
    <span>Scenes: {scene_count}</span>
    <span>Cost: ${cost}</span>
    <span>{now}</span>
</div>

<h2>Character Arcs</h2>
<table>
<tr><th>Character</th><th>Want/Need</th><th>Wound/Lie</th><th>Flaws</th><th>Voice</th><th>Avg</th></tr>
{char_rows}</table>

<h2>Act Structure</h2>
<table>
<tr><th>Act</th><th>Campbell</th><th>3-Act</th><th>Save Cat</th><th>Truby</th><th>Harmon</th><th>Kishoten.</th><th>Freytag</th><th>Char Web</th><th>Char Theme</th></tr>
{act_rows}</table>

<h2>Genre Contract</h2>
<table>
<tr><th>Trope Awareness</th><th>Archetype vs Cliche</th><th>Genre Contract</th><th>Subversion</th></tr>
<tr>{genre_row}</tr>
</table>

<div class="two-col">
<div>
<h2>Top Strengths</h2>
<table>
<tr><th>Principle</th><th>Avg</th><th>Best Scenes</th></tr>
{strengths}</table>
</div>
<div>
<h2>Areas for Improvement</h2>
<table>
<tr><th>Principle</th><th>Avg</th><th>Weakest Scenes</th></tr>
{weaknesses}</table>
</div>
</div>

<h2>Improvement Proposals</h2>
<table>
<tr><th>Principle</th><th>Lever</th><th>Change</th><th>Rationale</th><th>Status</th></tr>
{proposal_rows}</table>

<h2>Scene Averages</h2>
<table>
<tr><th>Scene</th><th>Avg Score</th></tr>
{scene_heatmap}</table>

</div>
</body>
</html>'''

    with open(report_file, 'w') as f:
        f.write(html)

    print(f'Generated scoring report: {report_file}', file=sys.stderr)


def build_score_pr_comment(cycle_dir: str, project_dir: str, cycle: str,
                           mode: str, scene_count: int, cost: str) -> str:
    """Build a markdown PR comment with scoring summary."""
    # Read project title
    project_title = 'Unknown'
    yaml_file = os.path.join(project_dir, 'storyforge.yaml')
    if os.path.isfile(yaml_file):
        with open(yaml_file) as f:
            for line in f:
                m = re.match(r'\s*title:\s*(.+)', line)
                if m:
                    project_title = m.group(1).strip().strip('"').strip("'")
                    break

    parts = [f'## Scoring Report \u2014 Cycle {cycle}',
             f'**{project_title}** | {mode} mode | {scene_count} scenes | ${cost}', '']

    # Character arcs
    char_file = os.path.join(cycle_dir, 'character-scores.csv')
    if os.path.isfile(char_file):
        header, rows = _read_csv(char_file)
        parts.append('### Character Arcs')
        parts.append('| Character | Want/Need | Wound/Lie | Flaws | Voice | Avg |')
        parts.append('|-----------|-----------|-----------|-------|-------|-----|')
        for row in rows:
            if not row or row[0] == 'character':
                continue
            vals = []
            cells = []
            for i in range(1, 5):
                v = row[i] if i < len(row) and row[i] else '0'
                try:
                    vals.append(float(v))
                except ValueError:
                    vals.append(0)
                cells.append(f'{_score_icon(int(float(v)))} {v}')
            avg = sum(vals) / max(len(vals), 1)
            parts.append(f'| {row[0]} | {" | ".join(cells)} | **{avg:.1f}** |')
        parts.append('')

    # Act structure
    act_file = os.path.join(cycle_dir, 'act-scores.csv')
    if os.path.isfile(act_file):
        header, rows = _read_csv(act_file)
        parts.append('### Act Structure')
        parts.append('| Act | Campbell | 3-Act | Save Cat | Truby | Harmon | Kishoten. | Freytag | Char Web | Theme |')
        parts.append('|-----|----------|-------|----------|-------|--------|-----------|---------|----------|-------|')
        for row in rows:
            if not row or row[0] == 'id':
                continue
            label = row[0].replace('act-', 'Part ')
            cells = ' | '.join(row[i] if i < len(row) else '' for i in range(1, len(header)))
            parts.append(f'| {label} | {cells} |')
        parts.append('')

    # Genre
    genre_file = os.path.join(cycle_dir, 'genre-scores.csv')
    if os.path.isfile(genre_file):
        header, rows = _read_csv(genre_file)
        if rows:
            row = rows[0]
            parts.append('### Genre Contract')
            parts.append('| Trope Awareness | Archetype vs Cliche | Genre Contract | Subversion |')
            parts.append('|-----------------|---------------------|----------------|------------|')
            cells = ' | '.join(row[i] if i < len(row) else '' for i in range(len(row)))
            parts.append(f'| {cells} |')
            parts.append('')

    # Strengths / weaknesses
    diag_file = os.path.join(cycle_dir, 'diagnosis.csv')
    if os.path.isfile(diag_file):
        header, rows = _read_csv(diag_file)
        scored = []
        for row in rows:
            if len(row) >= 4:
                try:
                    avg = float(row[2]) if row[2] else 0
                except ValueError:
                    avg = 0
                if avg > 0:
                    scored.append((avg, row[0].replace('_', ' '), row[3] if len(row) > 3 else ''))

        scored_asc = sorted(scored, key=lambda x: x[0])
        scored_desc = sorted(scored, key=lambda x: x[0], reverse=True)

        parts.append('### Top Strengths')
        parts.append('| Principle | Avg | Best Scenes |')
        parts.append('|-----------|-----|-------------|')
        for avg, prin, scenes in scored_desc[:5]:
            parts.append(f'| {prin} | {avg} | {scenes} |')
        parts.append('')

        parts.append('### Areas for Improvement')
        parts.append('| Principle | Avg | Weakest Scenes |')
        parts.append('|-----------|-----|----------------|')
        for avg, prin, scenes in scored_asc[:5]:
            parts.append(f'| {prin} | {avg} | {scenes} |')
        parts.append('')

    # Proposals
    proposals_file = os.path.join(cycle_dir, 'proposals.csv')
    if os.path.isfile(proposals_file):
        header, rows = _read_csv(proposals_file)
        data_rows = [r for r in rows if r and r[0] != 'id']
        if data_rows:
            parts.append(f'### Improvement Proposals ({len(data_rows)})')
            parts.append('| Principle | Lever | Change | Status |')
            parts.append('|-----------|-------|--------|--------|')
            for row in data_rows:
                prin = row[1].replace('_', ' ') if len(row) > 1 else ''
                lever = row[2].replace('_', ' ') if len(row) > 2 else ''
                change = row[4] if len(row) > 4 else ''
                status = row[6] if len(row) > 6 else 'pending'
                parts.append(f'| {prin} | {lever} | {change} | {status} |')
            parts.append('')

    parts.append('---')
    parts.append(f'*Report: `working/scores/cycle-{cycle}/report.html`*')

    return '\n'.join(parts)


# ============================================================================
# Brief fidelity scoring
# ============================================================================

FIDELITY_ELEMENTS = [
    'goal', 'conflict', 'outcome', 'crisis', 'decision',
    'key_actions', 'key_dialogue', 'emotions', 'knowledge',
]


def build_fidelity_prompt(scene_id: str, project_dir: str,
                          plugin_dir: str) -> str:
    """Build a brief fidelity evaluation prompt for a single scene.

    Reads the scene's brief data and prose, formats them into the
    brief-fidelity prompt template.

    Returns empty string if the scene has no brief or no prose.
    """
    from .elaborate import get_scene

    ref_dir = os.path.join(project_dir, 'reference')
    scene = get_scene(scene_id, ref_dir)
    if not scene:
        return ''

    # Check that brief data exists
    if not scene.get('goal', '').strip():
        return ''

    # Read prose
    scene_file = os.path.join(project_dir, 'scenes', f'{scene_id}.md')
    if not os.path.isfile(scene_file):
        return ''
    with open(scene_file, encoding='utf-8') as f:
        prose = f.read().strip()
    if not prose or len(prose) < 100:
        return ''

    # Format brief data
    brief_lines = []
    for key in ['goal', 'conflict', 'outcome', 'crisis', 'decision',
                'key_actions', 'key_dialogue', 'emotions', 'motifs',
                'knowledge_in', 'knowledge_out']:
        val = scene.get(key, '').strip()
        if val:
            brief_lines.append(f"**{key}:** {val}")

    brief_data = '\n'.join(brief_lines)

    # Read prompt template
    template_path = os.path.join(plugin_dir, 'scripts', 'prompts', 'scoring',
                                  'brief-fidelity.md')
    if os.path.isfile(template_path):
        with open(template_path, encoding='utf-8') as f:
            template = f.read()
    else:
        # Inline fallback
        template = (
            "Evaluate brief fidelity for scene {SCENE_ID}.\n\n"
            "Brief:\n{BRIEF_DATA}\n\nProse:\n{SCENE_PROSE}\n\n"
            "Output SCORES and RATIONALE blocks as pipe-delimited CSV."
        )

    prompt = template.replace('{BRIEF_DATA}', brief_data)
    prompt = prompt.replace('{SCENE_PROSE}', prose)
    prompt = prompt.replace('{SCENE_ID}', scene_id)

    return prompt


def parse_fidelity_response(response: str, scene_id: str) -> dict:
    """Parse a brief fidelity response into scores and rationale.

    Returns:
        {
            'scores': {'goal': 4, 'conflict': 3, ...},
            'rationale': [{'element': 'goal', 'score': 4, 'evidence': '...'}],
            'overall': 3.5,  # power mean
        }
    """
    scores = {}
    rationale = []

    # Parse line by line — look for CSV rows after SCORES and RATIONALE markers
    in_section = None
    for line in response.split('\n'):
        stripped = line.strip()
        if stripped.upper().startswith('SCORES'):
            in_section = 'scores'
            continue
        elif stripped.upper().startswith('RATIONALE'):
            in_section = 'rationale'
            continue
        elif not stripped:
            continue

        parts = stripped.split('|')

        if in_section == 'scores' and len(parts) >= 10:
            if parts[0].strip() == 'id':
                continue  # header row
            for i, element in enumerate(FIDELITY_ELEMENTS):
                try:
                    scores[element] = int(parts[i + 1].strip())
                except (ValueError, IndexError):
                    pass

        elif in_section == 'rationale' and len(parts) >= 4:
            if parts[0].strip() == 'id':
                continue  # header row
            try:
                rationale.append({
                    'element': parts[1].strip(),
                    'score': int(parts[2].strip()),
                    'evidence': parts[3].strip(),
                })
            except (ValueError, IndexError):
                pass

    # Calculate overall as power mean
    score_values = [float(v) for v in scores.values() if v > 0]
    overall = _power_mean(score_values) if score_values else 0.0

    return {
        'scene_id': scene_id,
        'scores': scores,
        'rationale': rationale,
        'overall': round(overall, 1),
    }


def write_fidelity_csv(results: list[dict], output_dir: str):
    """Write fidelity scores and rationale to CSV files.

    Args:
        results: List of parse_fidelity_response outputs.
        output_dir: Directory to write CSVs to.
    """
    os.makedirs(output_dir, exist_ok=True)

    # Scores CSV
    header = ['id'] + FIDELITY_ELEMENTS + ['overall']
    rows = []
    for r in results:
        row = [r['scene_id']]
        for el in FIDELITY_ELEMENTS:
            row.append(str(r['scores'].get(el, '')))
        row.append(str(r['overall']))
        rows.append(row)
    _write_csv(os.path.join(output_dir, 'fidelity-scores.csv'), header, rows)

    # Rationale CSV
    rat_header = ['id', 'element', 'score', 'evidence']
    rat_rows = []
    for r in results:
        for entry in r['rationale']:
            rat_rows.append([
                r['scene_id'],
                entry.get('element', ''),
                str(entry.get('score', '')),
                entry.get('evidence', ''),
            ])
    _write_csv(os.path.join(output_dir, 'fidelity-rationale.csv'),
               rat_header, rat_rows)


def generate_fidelity_diagnosis(results: list[dict]) -> list[dict]:
    """Analyze fidelity scores and identify patterns.

    Returns a list of findings, sorted by severity:
        {'element': str, 'avg_score': float, 'weak_scenes': list, 'priority': str}
    """
    from collections import defaultdict

    element_scores: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for r in results:
        for el, score in r['scores'].items():
            element_scores[el].append((r['scene_id'], score))

    findings = []
    for el, scene_scores in element_scores.items():
        scores = [s for _, s in scene_scores]
        avg = sum(scores) / len(scores) if scores else 0
        weak = [(sid, s) for sid, s in scene_scores if s <= 2]

        priority = 'low'
        if avg < 2.5:
            priority = 'high'
        elif avg < 3.5 or len(weak) > len(scores) * 0.3:
            priority = 'medium'

        findings.append({
            'element': el,
            'avg_score': round(avg, 1),
            'weak_scenes': [sid for sid, _ in weak],
            'weak_count': len(weak),
            'total_scenes': len(scores),
            'priority': priority,
        })

    findings.sort(key=lambda f: {'high': 0, 'medium': 1, 'low': 2}[f['priority']])
    return findings


# ============================================================================
# CLI interface
# ============================================================================

def main():
    """CLI entry point. Usage:

    python3 -m storyforge.scoring parse-output <text_file> <scores_out> <rationale_out> [--score-marker M] [--rationale-marker M]
    python3 -m storyforge.scoring merge <target> <source>
    python3 -m storyforge.scoring weighted-text <weights_file> [--exclude-section SECTION]
    python3 -m storyforge.scoring diagnose <scores_dir> <prev_dir> <weights_file>
    python3 -m storyforge.scoring propose <scores_dir> <weights_file>
    python3 -m storyforge.scoring effective-weight <weights_file> <principle>
    """
    if len(sys.argv) < 2:
        print('Usage: python3 -m storyforge.scoring <command> [args]', file=sys.stderr)
        sys.exit(1)

    command = sys.argv[1]

    if command == 'parse-output':
        if len(sys.argv) < 5:
            print('Usage: parse-output <text_file> <scores_out> <rationale_out> [--score-marker M] [--rationale-marker M]', file=sys.stderr)
            sys.exit(1)
        text_file = sys.argv[2]
        scores_out = sys.argv[3]
        rationale_out = sys.argv[4]

        # Parse optional flags
        score_marker = 'SCORES'
        rationale_marker = 'RATIONALE'
        i = 5
        while i < len(sys.argv):
            if sys.argv[i] == '--score-marker' and i + 1 < len(sys.argv):
                score_marker = sys.argv[i + 1]
                i += 2
            elif sys.argv[i] == '--rationale-marker' and i + 1 < len(sys.argv):
                rationale_marker = sys.argv[i + 1]
                i += 2
            else:
                i += 1

        with open(text_file) as f:
            text = f.read()

        scores, rationale = parse_score_output(text, score_marker, rationale_marker)

        if scores:
            with open(scores_out, 'w') as f:
                f.write(scores + '\n')
            print(f'Wrote scores: {scores_out}')
        else:
            print(f'WARNING: No {score_marker} block found', file=sys.stderr)
            sys.exit(1)

        if rationale:
            with open(rationale_out, 'w') as f:
                f.write(rationale + '\n')
            print(f'Wrote rationale: {rationale_out}')

    elif command == 'merge':
        if len(sys.argv) < 4:
            print('Usage: merge <target> <source>', file=sys.stderr)
            sys.exit(1)
        merge_score_files(sys.argv[2], sys.argv[3])
        print('ok')

    elif command == 'weighted-text':
        if len(sys.argv) < 3:
            print('Usage: weighted-text <weights_file> [--exclude-section SECTION]', file=sys.stderr)
            sys.exit(1)
        weights_file = sys.argv[2]
        exclude_section = ''
        if len(sys.argv) > 3 and sys.argv[3] == '--exclude-section' and len(sys.argv) > 4:
            exclude_section = sys.argv[4]
        print(build_weighted_text(weights_file, exclude_section))

    elif command == 'diagnose':
        if len(sys.argv) < 5:
            print('Usage: diagnose <scores_dir> <prev_dir> <weights_file>', file=sys.stderr)
            sys.exit(1)
        prev_dir = sys.argv[3] if sys.argv[3] != '-' else ''
        generate_diagnosis(sys.argv[2], prev_dir, sys.argv[4])
        print('ok')

    elif command == 'propose':
        if len(sys.argv) < 4:
            print('Usage: propose <scores_dir> <weights_file>', file=sys.stderr)
            sys.exit(1)
        generate_proposals(sys.argv[2], sys.argv[3])
        print('ok')

    elif command == 'effective-weight':
        if len(sys.argv) < 4:
            print('Usage: effective-weight <weights_file> <principle>', file=sys.stderr)
            sys.exit(1)
        print(get_effective_weight(sys.argv[2], sys.argv[3]))

    elif command == 'parse-evaluation':
        # Parse single-pass scene evaluation into pivoted CSVs
        # Usage: parse-evaluation <text_file> <scores_out> <rationale_out> <scene_id> [--diagnostics <csv>]
        if len(sys.argv) < 6:
            print('Usage: parse-evaluation <text_file> <scores_out> '
                  '<rationale_out> <scene_id> [--diagnostics <csv>]',
                  file=sys.stderr)
            sys.exit(1)

        text_file = sys.argv[2]
        scores_out = sys.argv[3]
        rationale_out = sys.argv[4]
        scene_id = sys.argv[5]
        diag_csv = ''

        i = 6
        while i < len(sys.argv):
            if sys.argv[i] == '--diagnostics' and i + 1 < len(sys.argv):
                diag_csv = sys.argv[i + 1]
                i += 2
            else:
                i += 1

        with open(text_file) as f:
            text = f.read()

        scores_csv, rationale_csv = parse_scene_evaluation(
            text, scene_id, diagnostics_csv=diag_csv)

        if scores_csv:
            with open(scores_out, 'w') as f:
                f.write(scores_csv + '\n')
        else:
            print('WARNING: No SCORES block found', file=sys.stderr)
            sys.exit(1)

        if rationale_csv:
            with open(rationale_out, 'w') as f:
                f.write(rationale_csv + '\n')

        print('ok')

    elif command == 'init-weights':
        # Usage: init-weights <project_dir> <plugin_dir>
        if len(sys.argv) < 4:
            print('Usage: init-weights <project_dir> <plugin_dir>', file=sys.stderr)
            sys.exit(1)
        init_craft_weights(sys.argv[2], sys.argv[3])
        print('ok')

    elif command == 'build-evaluation-criteria':
        # Usage: build-evaluation-criteria <diagnostics_csv> <guide_file>
        if len(sys.argv) < 4:
            print('Usage: build-evaluation-criteria <diagnostics_csv> <guide_file>',
                  file=sys.stderr)
            sys.exit(1)
        result = build_evaluation_criteria(sys.argv[2], sys.argv[3])
        if result:
            print(result)
        else:
            sys.exit(1)

    elif command == 'extract-rubric-section':
        # Usage: extract-rubric-section <section_name> <plugin_dir>
        if len(sys.argv) < 4:
            print('Usage: extract-rubric-section <section_name> <plugin_dir>',
                  file=sys.stderr)
            sys.exit(1)
        result = extract_rubric_section(sys.argv[2], sys.argv[3])
        if result:
            print(result)

    elif command == 'collect-exemplars':
        # Usage: collect-exemplars <scores_dir> <project_dir> <cycle>
        if len(sys.argv) < 5:
            print('Usage: collect-exemplars <scores_dir> <project_dir> <cycle>',
                  file=sys.stderr)
            sys.exit(1)
        collect_exemplars(sys.argv[2], sys.argv[3], sys.argv[4])
        print('ok')

    elif command == 'check-validated-patterns':
        # Usage: check-validated-patterns <project_dir>
        if len(sys.argv) < 3:
            print('Usage: check-validated-patterns <project_dir>', file=sys.stderr)
            sys.exit(1)
        result = check_validated_patterns(sys.argv[2])
        if result:
            print(result)

    elif command == 'generate-report':
        # Usage: generate-report <cycle_dir> <project_dir> <cycle> <mode> <scene_count> <cost>
        if len(sys.argv) < 8:
            print('Usage: generate-report <cycle_dir> <project_dir> <cycle> <mode> <scene_count> <cost>',
                  file=sys.stderr)
            sys.exit(1)
        generate_score_report(sys.argv[2], sys.argv[3], sys.argv[4],
                             sys.argv[5], int(sys.argv[6]), sys.argv[7])
        print('ok')

    elif command == 'pr-comment':
        # Usage: pr-comment <cycle_dir> <project_dir> <cycle> <mode> <scene_count> <cost>
        if len(sys.argv) < 8:
            print('Usage: pr-comment <cycle_dir> <project_dir> <cycle> <mode> <scene_count> <cost>',
                  file=sys.stderr)
            sys.exit(1)
        result = build_score_pr_comment(sys.argv[2], sys.argv[3], sys.argv[4],
                                        sys.argv[5], int(sys.argv[6]), sys.argv[7])
        print(result)

    else:
        print(f'Unknown command: {command}', file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
