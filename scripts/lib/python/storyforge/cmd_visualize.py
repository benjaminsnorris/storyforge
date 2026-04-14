"""storyforge visualize -- Manuscript visualization dashboard.

Reads scene metadata, intent, and score CSVs to generate an interactive
self-contained HTML dashboard showing multiple visualizations.

The HTML template lives in templates/dashboard.html. This module loads
dashboard data via storyforge.visualize, injects it as JSON into the
template, and writes the result to working/dashboard.html.

Usage:
    storyforge visualize              # Generate dashboard
    storyforge visualize --open       # Generate and open in browser
    storyforge visualize --dry-run    # Show what would be generated
"""

import argparse
import json
import os
import platform
import subprocess
import sys

from storyforge.common import (
    detect_project_root, log, read_yaml_field, get_plugin_dir,
)
from storyforge.git import commit_and_push, ensure_on_branch


# ============================================================================
# Argument parsing
# ============================================================================

def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog='storyforge visualize',
        description='Generate an interactive HTML dashboard from manuscript data.',
    )
    parser.add_argument('--open', action='store_true',
                        help='Open the dashboard in the default browser')
    parser.add_argument('--dry-run', action='store_true',
                        help='Show what would be generated without writing')
    return parser.parse_args(argv)


# ============================================================================
# Template loading
# ============================================================================

def _find_template():
    """Locate the dashboard HTML template.

    Searches in order:
        1. templates/dashboard.html (project-level override)
        2. <plugin_dir>/templates/dashboard.html (bundled with plugin)
    """
    plugin_dir = get_plugin_dir()
    template_path = os.path.join(plugin_dir, 'templates', 'dashboard.html')
    if os.path.isfile(template_path):
        return template_path

    # Shouldn't happen, but provide a clear error
    return None


def _load_template():
    """Load the HTML template content. Exits on failure."""
    path = _find_template()
    if not path:
        log('ERROR: Dashboard template not found at templates/dashboard.html')
        log('The template should be in the plugin\'s templates/ directory.')
        sys.exit(1)

    with open(path, encoding='utf-8') as f:
        return f.read()


# ============================================================================
# Data injection
# ============================================================================

def _build_data_injection(data_json):
    """Build the JavaScript data injection block.

    This replaces the heredoc sections in the bash script that inject
    JSON data between the HTML template and the JS visualization code.
    """
    return f"""const _DATA = {data_json};
const SCENES = _DATA.scenes;
const INTENTS = _DATA.intents;
const CHARACTERS = _DATA.characters;
const MOTIF_TAXONOMY = _DATA.motif_taxonomy;
const LOCATIONS = _DATA.locations;
const VALUES = _DATA.values || [];
const MICE_THREADS = _DATA.mice_threads || [];
const KNOWLEDGE = _DATA.knowledge || [];
const SCORES = _DATA.scores;
const WEIGHTS = _DATA.weights;
const NARRATIVE_SCORES = _DATA.narrative_scores;
const PROJECT = _DATA.project;
const SCENE_RATIONALES = _DATA.scene_rationales;
const ACT_SCORES = _DATA.act_scores;
const ACT_RATIONALES = _DATA.act_rationales;
const CHARACTER_SCORES = _DATA.character_scores;
const CHARACTER_RATIONALES = _DATA.character_rationales;
const GENRE_SCORES = _DATA.genre_scores;
const GENRE_RATIONALES = _DATA.genre_rationales;
const NARRATIVE_RATIONALES = _DATA.narrative_rationales;
const BRIEFS = _DATA.briefs || [];
const FIDELITY_SCORES = _DATA.fidelity_scores || [];
const FIDELITY_RATIONALES = _DATA.fidelity_rationales || [];
const STRUCTURAL_SCORES = _DATA.structural_scores || [];
const REPETITION_SCORES = _DATA.repetition_scores || [];
const BRIEF_QUALITY = _DATA.brief_quality || [];

// Build brief quality lookup: scene_id -> Set of issue types
const briefQualityByScene = {{}};
const briefQualityDetails = {{}};
BRIEF_QUALITY.forEach(bq => {{
    if (!briefQualityByScene[bq.scene_id]) {{
        briefQualityByScene[bq.scene_id] = new Set();
        briefQualityDetails[bq.scene_id] = [];
    }}
    briefQualityByScene[bq.scene_id].add(bq.issue);
    briefQualityDetails[bq.scene_id].push(bq);
}});

// Merge briefs data into intents for charts that need it
if (BRIEFS.length) {{
    const briefsById = {{}};
    BRIEFS.forEach(b => {{ briefsById[b.id] = b; }});
    INTENTS.forEach(intent => {{
        const brief = briefsById[intent.id];
        if (brief) {{
            if (!intent.motifs && brief.motifs) intent.motifs = brief.motifs;
            if (!intent.notes && brief.key_actions) intent.notes = brief.key_actions;
        }}
    }});
}}"""


def _inject_data(template, data_json):
    """Inject JSON data into the HTML template.

    The template contains a marker line '// DATA_INJECTION_POINT' where
    the data constants should be inserted.
    """
    injection = _build_data_injection(data_json)

    # Replace the injection point marker
    if '// DATA_INJECTION_POINT' in template:
        return template.replace('// DATA_INJECTION_POINT', injection)

    # Fallback: if no marker, this is likely the original template format
    # where the data goes right after the <script> tag at the end of HTML
    log('WARNING: No DATA_INJECTION_POINT marker in template, using fallback injection')
    # Insert after the DATA INJECTION comment
    marker = '// ============================================================================\n// DATA INJECTION'
    if marker in template:
        idx = template.index(marker)
        # Find the next line after the block comment
        end_idx = template.index('\n', template.index('\n', idx) + 1) + 1
        return template[:end_idx] + injection + '\n' + template[end_idx:]

    log('ERROR: Could not find injection point in template')
    sys.exit(1)


# ============================================================================
# Main
# ============================================================================

def main(argv=None):
    args = parse_args(argv or [])

    project_dir = detect_project_root()
    ensure_on_branch('visualize', project_dir)

    metadata_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
    intent_csv = os.path.join(project_dir, 'reference', 'scene-intent.csv')
    scores_csv = os.path.join(project_dir, 'working', 'scores', 'latest', 'scene-scores.csv')
    weights_csv = os.path.join(project_dir, 'working', 'craft-weights.csv')
    chapter_map_csv = os.path.join(project_dir, 'reference', 'chapter-map.csv')
    dashboard_file = os.path.join(project_dir, 'working', 'dashboard.html')

    # Validate required files
    if not os.path.isfile(metadata_csv):
        print(f'ERROR: reference/scenes.csv not found at {metadata_csv}', file=sys.stderr)
        sys.exit(1)
    if not os.path.isfile(intent_csv):
        print(f'ERROR: reference/scene-intent.csv not found at {intent_csv}', file=sys.stderr)
        sys.exit(1)

    # Read project info
    project_title = read_yaml_field('project.title', project_dir) or \
                    read_yaml_field('title', project_dir) or 'Unknown'
    project_genre = read_yaml_field('project.genre', project_dir) or \
                    read_yaml_field('genre', project_dir) or ''

    # Count scenes
    with open(metadata_csv) as f:
        scene_count = sum(1 for line in f) - 1  # subtract header

    # Dry run
    if args.dry_run:
        log(f'DRY RUN -- would generate dashboard at {dashboard_file}')
        log(f'  Project: {project_title}')
        log(f'  Scenes: {scene_count}')
        log(f'  Metadata: {metadata_csv}')
        log(f'  Intent: {intent_csv}')
        log(f'  Scores: {scores_csv if os.path.isfile(scores_csv) else "(not found)"}')
        log(f'  Weights: {weights_csv if os.path.isfile(weights_csv) else "(not found)"}')
        log(f'  Chapter map: {chapter_map_csv if os.path.isfile(chapter_map_csv) else "(not found)"}')
        return

    log(f'Generating manuscript dashboard for {project_title}...')

    # Load dashboard data via the visualize module
    from storyforge.visualize import load_dashboard_data
    data = load_dashboard_data(project_dir)
    data_json = json.dumps(data, ensure_ascii=False)

    # Load and populate template
    template = _load_template()
    html = _inject_data(template, data_json)

    # Write dashboard
    os.makedirs(os.path.dirname(dashboard_file), exist_ok=True)
    with open(dashboard_file, 'w', encoding='utf-8') as f:
        f.write(html)

    log(f'Dashboard generated: {dashboard_file}')

    # Commit and push
    commit_and_push(
        project_dir,
        'Visualize: generate manuscript dashboard',
        ['working/dashboard.html'],
    )

    # Open in browser
    if args.open:
        system = platform.system()
        if system == 'Darwin':
            subprocess.run(['open', dashboard_file], check=False)
            log('Opened in browser.')
        elif system == 'Linux':
            subprocess.run(['xdg-open', dashboard_file], check=False)
            log('Opened in browser.')
        else:
            log(f'WARNING: Could not find browser opener. Open manually: {dashboard_file}')
