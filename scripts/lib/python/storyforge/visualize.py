"""Dashboard data loading for storyforge-visualize.

Replaces fragile awk-based CSV-to-JSON conversion with reliable Python
parsing. The bash script continues to handle HTML template assembly but
calls this module for data loading.

Usage from bash:
    python3 -m storyforge.visualize data "$PROJECT_DIR"
"""

import json
import os
import sys
from datetime import datetime


def csv_to_records(csv_file: str) -> list[dict]:
    """Read a pipe-delimited CSV file into a list of dicts.

    Header row becomes dict keys. Missing files or empty files return [].
    Values are always strings (matching the awk behavior).
    HTML-unsafe characters (<, >) are escaped for safe injection into
    script tags.
    """
    if not csv_file or not os.path.isfile(csv_file):
        return []

    try:
        with open(csv_file, newline='', encoding='utf-8') as f:
            raw = f.read().replace('\r\n', '\n').replace('\r', '')
        lines = raw.splitlines()
    except (OSError, UnicodeDecodeError):
        return []

    if len(lines) < 2:
        return []

    headers = lines[0].split('|')
    records = []

    for line in lines[1:]:
        if not line.strip():
            continue
        fields = line.split('|')
        row = {}
        for i, header in enumerate(headers):
            val = fields[i] if i < len(fields) else ''
            # Escape HTML-unsafe characters for safe script-tag injection
            val = val.replace('<', '\\u003c').replace('>', '\\u003e')
            row[header] = val
        records.append(row)

    return records


def _read_yaml_field(project_dir: str, field: str) -> str:
    """Minimal YAML field reader — handles dotted keys like project.title.

    Parses simple key: value lines. For dotted keys (e.g., project.title),
    looks for 'title' indented under 'project:'.
    """
    yaml_path = os.path.join(project_dir, 'storyforge.yaml')
    if not os.path.isfile(yaml_path):
        return ''

    try:
        with open(yaml_path, encoding='utf-8') as f:
            lines = f.readlines()
    except OSError:
        return ''

    parts = field.split('.')

    if len(parts) == 1:
        # Simple top-level key
        for line in lines:
            stripped = line.strip()
            if stripped.startswith(f'{parts[0]}:'):
                val = stripped[len(parts[0]) + 1:].strip()
                # Remove surrounding quotes
                if len(val) >= 2 and val[0] in ('"', "'") and val[-1] == val[0]:
                    val = val[1:-1]
                return val
        return ''

    # Dotted key: find parent section, then child
    parent = parts[0]
    child = parts[1]
    in_section = False

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            continue

        # Check indentation
        indent = len(line) - len(line.lstrip())

        if indent == 0 and stripped.startswith(f'{parent}:'):
            in_section = True
            continue

        if in_section:
            if indent == 0:
                # Left the section
                in_section = False
                continue
            if stripped.startswith(f'{child}:'):
                val = stripped[len(child) + 1:].strip()
                if len(val) >= 2 and val[0] in ('"', "'") and val[-1] == val[0]:
                    val = val[1:-1]
                return val

    return ''


def _compute_brief_quality(project_dir: str) -> list[dict]:
    """Run brief quality detection and return JSON-safe results.

    Returns a list of issue dicts, each with: scene_id, field, issue,
    plus type-specific metrics (beat_count, char_count, etc.).
    Returns [] if detection fails or data is missing.
    """
    try:
        from storyforge.elaborate import _read_csv_as_map
        from storyforge.hone import detect_brief_issues, detect_gaps
    except ImportError:
        return []

    ref_dir = os.path.join(project_dir, 'reference')
    scenes_path = os.path.join(ref_dir, 'scenes.csv')
    briefs_path = os.path.join(ref_dir, 'scene-briefs.csv')
    intent_path = os.path.join(ref_dir, 'scene-intent.csv')

    if not os.path.isfile(scenes_path) or not os.path.isfile(briefs_path):
        return []

    try:
        scenes_map = _read_csv_as_map(scenes_path)
        briefs_map = _read_csv_as_map(briefs_path)
        intent_map = _read_csv_as_map(intent_path) if os.path.isfile(intent_path) else {}

        issues = detect_brief_issues(briefs_map, scenes_map)
        gaps = detect_gaps(scenes_map, intent_map, briefs_map)

        results = []
        for i in issues:
            entry = {
                'scene_id': i['scene_id'],
                'field': i['field'],
                'issue': i['issue'],
            }
            if i['issue'] == 'overspecified':
                entry['beat_count'] = i.get('beat_count', 0)
                entry['target_words'] = i.get('target_words', 0)
            elif i['issue'] == 'verbose':
                entry['char_count'] = i.get('char_count', 0)
                entry['max_chars'] = i.get('max_chars', 0)
            elif i['issue'] == 'abstract':
                entry['abstract_count'] = i.get('abstract_count', 0)
                entry['concrete_count'] = i.get('concrete_count', 0)
            results.append(entry)

        for g in gaps:
            results.append({
                'scene_id': g['scene_id'],
                'field': g['field'],
                'issue': 'gap',
            })

        return results
    except Exception:
        return []


def load_dashboard_data(project_dir: str) -> dict:
    """Load all CSV data needed for the manuscript dashboard.

    Args:
        project_dir: Path to the novel project root.

    Returns:
        Dict with keys: scenes, intents, characters, motif_taxonomy,
        locations, scores, weights, narrative_scores, project.
        All values are JSON-serializable.
    """
    # Three-file model: scenes.csv + scene-intent.csv + scene-briefs.csv
    metadata_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
    intent_csv = os.path.join(project_dir, 'reference', 'scene-intent.csv')
    briefs_csv = os.path.join(project_dir, 'reference', 'scene-briefs.csv')
    scores_csv = os.path.join(project_dir, 'working/scores/latest/scene-scores.csv')
    weights_csv = os.path.join(project_dir, 'working/craft-weights.csv')
    characters_csv = os.path.join(project_dir, 'reference/characters.csv')
    motif_csv = os.path.join(project_dir, 'reference/motif-taxonomy.csv')
    locations_csv = os.path.join(project_dir, 'reference/locations.csv')
    values_csv = os.path.join(project_dir, 'reference/values.csv')
    mice_threads_csv = os.path.join(project_dir, 'reference/mice-threads.csv')
    knowledge_csv = os.path.join(project_dir, 'reference/knowledge.csv')
    structural_csv = os.path.join(project_dir, 'working/scores/structural-latest.csv')
    fidelity_csv = os.path.join(project_dir, 'working/scores/latest/fidelity-scores.csv')
    fidelity_rationale_csv = os.path.join(project_dir, 'working/scores/latest/fidelity-rationale.csv')
    narrative_csv = os.path.join(project_dir, 'working/scores/latest/narrative-scores.csv')
    scene_rationale_csv = os.path.join(project_dir, 'working/scores/latest/scene-rationale.csv')
    act_scores_csv = os.path.join(project_dir, 'working/scores/latest/act-scores.csv')
    act_rationale_csv = os.path.join(project_dir, 'working/scores/latest/act-rationale.csv')
    character_scores_csv = os.path.join(project_dir, 'working/scores/latest/character-scores.csv')
    character_rationale_csv = os.path.join(project_dir, 'working/scores/latest/character-rationale.csv')
    genre_scores_csv = os.path.join(project_dir, 'working/scores/latest/genre-scores.csv')
    genre_rationale_csv = os.path.join(project_dir, 'working/scores/latest/genre-rationale.csv')
    narrative_rationale_csv = os.path.join(project_dir, 'working/scores/latest/narrative-rationale.csv')

    scenes = csv_to_records(metadata_csv)

    # Normalize 'setting' column to 'location' for dashboard JS compatibility
    for scene in scenes:
        if 'setting' in scene and 'location' not in scene:
            scene['location'] = scene['setting']

    # Build seq ordering map from scenes for sorting intents/briefs
    seq_by_id = {}
    for scene in scenes:
        try:
            seq_by_id[scene.get('id', '')] = int(scene.get('seq', 0))
        except (ValueError, TypeError):
            pass

    title = _read_yaml_field(project_dir, 'project.title')
    if not title:
        title = _read_yaml_field(project_dir, 'title')
    if not title:
        title = 'Unknown'

    genre = _read_yaml_field(project_dir, 'project.genre')
    if not genre:
        genre = _read_yaml_field(project_dir, 'genre')

    # Compute total word count
    total_words = sum(int(s.get('word_count', 0) or 0) for s in scenes)
    target_words = _read_yaml_field(project_dir, 'project.target_words') or ''
    phase = _read_yaml_field(project_dir, 'phase') or ''

    # Sort intents and briefs by scene seq order (extraction may write alphabetically)
    intents = csv_to_records(intent_csv)
    intents.sort(key=lambda r: seq_by_id.get(r.get('id', ''), 999))
    briefs = csv_to_records(briefs_csv)
    briefs.sort(key=lambda r: seq_by_id.get(r.get('id', ''), 999))

    # Brief quality detection (lightweight, no API calls)
    brief_quality = _compute_brief_quality(project_dir)

    return {
        'scenes': scenes,
        'intents': intents,
        'briefs': briefs,
        'characters': csv_to_records(characters_csv),
        'motif_taxonomy': csv_to_records(motif_csv),
        'locations': csv_to_records(locations_csv),
        'values': csv_to_records(values_csv),
        'mice_threads': csv_to_records(mice_threads_csv),
        'knowledge': csv_to_records(knowledge_csv),
        'scores': csv_to_records(scores_csv),
        'weights': csv_to_records(weights_csv),
        'narrative_scores': csv_to_records(narrative_csv),
        'scene_rationales': csv_to_records(scene_rationale_csv),
        'act_scores': csv_to_records(act_scores_csv),
        'act_rationales': csv_to_records(act_rationale_csv),
        'character_scores': csv_to_records(character_scores_csv),
        'character_rationales': csv_to_records(character_rationale_csv),
        'genre_scores': csv_to_records(genre_scores_csv),
        'genre_rationales': csv_to_records(genre_rationale_csv),
        'narrative_rationales': csv_to_records(narrative_rationale_csv),
        'fidelity_scores': csv_to_records(fidelity_csv),
        'fidelity_rationales': csv_to_records(fidelity_rationale_csv),
        'structural_scores': csv_to_records(structural_csv),
        'brief_quality': brief_quality,
        'project': {
            'title': title,
            'genre': genre,
            'phase': phase,
            'scene_count': str(len(scenes)),
            'total_words': str(total_words),
            'target_words': target_words,
            'generated': datetime.now().strftime('%Y-%m-%d %H:%M'),
        },
    }


# --- CLI interface for calling from bash ---

def main():
    """CLI entry point.

    Usage:
        python3 -m storyforge.visualize data <project_dir>
    """
    if len(sys.argv) < 2:
        print('Usage: python3 -m storyforge.visualize <command> [args]', file=sys.stderr)
        sys.exit(1)

    command = sys.argv[1]

    if command == 'data':
        if len(sys.argv) < 3:
            print('Usage: python3 -m storyforge.visualize data <project_dir>', file=sys.stderr)
            sys.exit(1)
        project_dir = sys.argv[2]
        data = load_dashboard_data(project_dir)
        json.dump(data, sys.stdout, ensure_ascii=False)

    else:
        print(f'Unknown command: {command}', file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
