"""Quick queries about project state.

Provides functions to answer common questions: current cycle, latest
scores/evaluation/review/plan paths, project config, and a combined
project summary.

Usage from bash:
    python3 -m storyforge.project summary <project_dir>
    python3 -m storyforge.project cycle <project_dir>
    python3 -m storyforge.project scores <project_dir>
    python3 -m storyforge.project evaluation <project_dir>
    python3 -m storyforge.project review <project_dir>
    python3 -m storyforge.project plan <project_dir>
    python3 -m storyforge.project history <project_dir>
"""

import json
import os
import re
import sys

from .prompts import read_yaml_field, _read_csv_header_and_rows


# ============================================================================
# CSV helper (local, avoids HTML-escaping from visualize.csv_to_records)
# ============================================================================

def _csv_to_records(csv_file: str) -> list[dict]:
    """Read a pipe-delimited CSV file into a list of dicts.

    Unlike visualize.csv_to_records, this does NOT escape HTML characters
    since the data is used programmatically, not injected into HTML.
    """
    if not csv_file or not os.path.isfile(csv_file):
        return []

    try:
        header, rows = _read_csv_header_and_rows(csv_file)
    except (OSError, UnicodeDecodeError):
        return []

    if not header or not rows:
        return []

    records = []
    for row in rows:
        record = {}
        for i, h in enumerate(header):
            record[h] = row[i] if i < len(row) else ''
        records.append(record)

    return records


# ============================================================================
# Pipeline / cycle queries
# ============================================================================

def _pipeline_csv(project_dir: str) -> str:
    """Return the path to pipeline.csv."""
    return os.path.join(project_dir, 'working', 'pipeline.csv')


def cycle_history(project_dir: str) -> list[dict]:
    """Return all cycles from pipeline.csv as a list of dicts.

    Keys: cycle, started, status, evaluation, plan, review,
    recommendations, summary.

    Returns:
        List of cycle dicts (may be empty).
    """
    return _csv_to_records(_pipeline_csv(project_dir))


def current_cycle(project_dir: str) -> dict | None:
    """Return the latest cycle row from pipeline.csv as a dict.

    Returns:
        Dict with cycle fields, or None if no cycles exist.
    """
    cycles = cycle_history(project_dir)
    if not cycles:
        return None
    return cycles[-1]


# ============================================================================
# Latest artifact paths
# ============================================================================

def latest_scores(project_dir: str) -> str | None:
    """Return path to the latest scores directory.

    Checks ``working/scores/latest`` symlink first, then falls back to
    the highest-numbered ``working/scores/cycle-N/`` directory.

    Returns:
        Absolute path string, or None if no scores exist.
    """
    scores_dir = os.path.join(project_dir, 'working', 'scores')

    # Check symlink first
    latest_link = os.path.join(scores_dir, 'latest')
    if os.path.islink(latest_link) and os.path.isdir(latest_link):
        return os.path.realpath(latest_link)

    # Fall back to highest cycle-N directory
    if not os.path.isdir(scores_dir):
        return None

    cycle_dirs = []
    for entry in os.listdir(scores_dir):
        m = re.match(r'^cycle-(\d+)$', entry)
        if m:
            full = os.path.join(scores_dir, entry)
            if os.path.isdir(full):
                cycle_dirs.append((int(m.group(1)), full))

    if not cycle_dirs:
        return None

    cycle_dirs.sort(key=lambda x: x[0])
    return cycle_dirs[-1][1]


def latest_evaluation(project_dir: str) -> str | None:
    """Return path to the latest evaluation directory.

    Checks pipeline.csv first for the current cycle's evaluation field,
    then falls back to the most recently modified ``working/evaluations/eval-*/``
    directory.

    Returns:
        Absolute path string, or None if no evaluations exist.
    """
    # Try pipeline.csv first
    cycle = current_cycle(project_dir)
    if cycle:
        eval_field = cycle.get('evaluation', '')
        if eval_field:
            eval_path = os.path.join(project_dir, eval_field)
            if os.path.isdir(eval_path):
                return os.path.abspath(eval_path)

    # Fall back to most recent eval-* by modification time
    evals_dir = os.path.join(project_dir, 'working', 'evaluations')
    if not os.path.isdir(evals_dir):
        return None

    eval_dirs = []
    for entry in os.listdir(evals_dir):
        if entry.startswith('eval-'):
            full = os.path.join(evals_dir, entry)
            if os.path.isdir(full):
                eval_dirs.append((os.path.getmtime(full), full))

    if not eval_dirs:
        return None

    eval_dirs.sort(key=lambda x: x[0])
    return eval_dirs[-1][1]


def latest_review(project_dir: str) -> str | None:
    """Return path to the latest review file in ``working/reviews/``.

    Selects the most recently modified file.

    Returns:
        Absolute path string, or None if no reviews exist.
    """
    reviews_dir = os.path.join(project_dir, 'working', 'reviews')
    if not os.path.isdir(reviews_dir):
        return None

    files = []
    for entry in os.listdir(reviews_dir):
        full = os.path.join(reviews_dir, entry)
        if os.path.isfile(full):
            files.append((os.path.getmtime(full), full))

    if not files:
        return None

    files.sort(key=lambda x: x[0])
    return files[-1][1]


def latest_plan(project_dir: str) -> str | None:
    """Return path to the latest revision plan in ``working/plans/``.

    Selects the most recently modified file.

    Returns:
        Absolute path string, or None if no plans exist.
    """
    plans_dir = os.path.join(project_dir, 'working', 'plans')
    if not os.path.isdir(plans_dir):
        return None

    files = []
    for entry in os.listdir(plans_dir):
        full = os.path.join(plans_dir, entry)
        if os.path.isfile(full):
            files.append((os.path.getmtime(full), full))

    if not files:
        return None

    files.sort(key=lambda x: x[0])
    return files[-1][1]


# ============================================================================
# Project config and summary
# ============================================================================

def project_config(project_dir: str) -> dict:
    """Read storyforge.yaml and return key project fields.

    Returns:
        Dict with keys: title, genre, logline, phase, coaching_level,
        target_words. Missing fields are empty strings.
    """
    yaml_file = os.path.join(project_dir, 'storyforge.yaml')

    def _field(dotted: str, flat: str = '') -> str:
        val = read_yaml_field(yaml_file, dotted)
        if not val and flat:
            val = read_yaml_field(yaml_file, flat)
        return val

    return {
        'title': _field('project.title', 'title'),
        'genre': _field('project.genre', 'genre'),
        'logline': _field('project.logline', 'logline'),
        'phase': _field('project.phase', 'phase'),
        'coaching_level': _field('project.coaching_level', 'coaching_level'),
        'target_words': _field('project.target_words', 'target_words'),
    }


def _count_scenes(project_dir: str) -> int:
    """Count scene files in scenes/ directory."""
    scenes_dir = os.path.join(project_dir, 'scenes')
    if not os.path.isdir(scenes_dir):
        return 0
    return sum(1 for f in os.listdir(scenes_dir)
               if f.endswith('.md') and os.path.isfile(os.path.join(scenes_dir, f)))


def _count_chapters(project_dir: str) -> int:
    """Count chapters from reference/chapter-map.csv."""
    chapter_csv = os.path.join(project_dir, 'reference', 'chapter-map.csv')
    records = _csv_to_records(chapter_csv)
    return len(records)


def _manuscript_word_count(project_dir: str) -> int:
    """Sum word counts across all scene files."""
    scenes_dir = os.path.join(project_dir, 'scenes')
    if not os.path.isdir(scenes_dir):
        return 0

    total = 0
    for fname in os.listdir(scenes_dir):
        if not fname.endswith('.md'):
            continue
        fpath = os.path.join(scenes_dir, fname)
        if not os.path.isfile(fpath):
            continue
        try:
            with open(fpath, encoding='utf-8') as f:
                total += len(f.read().split())
        except (OSError, UnicodeDecodeError):
            pass
    return total


def project_summary(project_dir: str) -> dict:
    """Comprehensive project summary.

    Combines project_config, current_cycle, and counts (scenes,
    chapters, word count).

    Returns:
        Dict with config fields, cycle info, and counts.
    """
    config = project_config(project_dir)
    cycle = current_cycle(project_dir)

    summary = dict(config)
    summary['scene_count'] = _count_scenes(project_dir)
    summary['chapter_count'] = _count_chapters(project_dir)
    summary['word_count'] = _manuscript_word_count(project_dir)

    if cycle:
        summary['current_cycle'] = cycle
    else:
        summary['current_cycle'] = None

    scores_path = latest_scores(project_dir)
    summary['latest_scores'] = scores_path

    eval_path = latest_evaluation(project_dir)
    summary['latest_evaluation'] = eval_path

    review_path = latest_review(project_dir)
    summary['latest_review'] = review_path

    plan_path = latest_plan(project_dir)
    summary['latest_plan'] = plan_path

    return summary


# ============================================================================
# CLI interface
# ============================================================================

def main():
    """CLI entry point.

    Usage:
        python3 -m storyforge.project summary <project_dir>
        python3 -m storyforge.project cycle <project_dir>
        python3 -m storyforge.project scores <project_dir>
        python3 -m storyforge.project evaluation <project_dir>
        python3 -m storyforge.project review <project_dir>
        python3 -m storyforge.project plan <project_dir>
        python3 -m storyforge.project history <project_dir>
    """
    if len(sys.argv) < 3:
        print('Usage: python3 -m storyforge.project <command> <project_dir>',
              file=sys.stderr)
        sys.exit(1)

    command = sys.argv[1]
    project_dir = sys.argv[2]

    if command == 'summary':
        data = project_summary(project_dir)
        json.dump(data, sys.stdout, indent=2, ensure_ascii=False)
        print()

    elif command == 'cycle':
        cycle = current_cycle(project_dir)
        if cycle:
            json.dump(cycle, sys.stdout, indent=2, ensure_ascii=False)
            print()
        else:
            print('null')

    elif command == 'scores':
        path = latest_scores(project_dir)
        if path:
            print(path)

    elif command == 'evaluation':
        path = latest_evaluation(project_dir)
        if path:
            print(path)

    elif command == 'review':
        path = latest_review(project_dir)
        if path:
            print(path)

    elif command == 'plan':
        path = latest_plan(project_dir)
        if path:
            print(path)

    elif command == 'history':
        cycles = cycle_history(project_dir)
        json.dump(cycles, sys.stdout, indent=2, ensure_ascii=False)
        print()

    else:
        print(f'Unknown command: {command}', file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
