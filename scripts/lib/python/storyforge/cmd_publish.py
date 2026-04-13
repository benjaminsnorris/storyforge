"""storyforge publish -- Publish a book to the Bookshelf app via API.

Generates a publish manifest from the scene files and chapter map, authenticates
with Supabase, and PUTs the manifest to the Bookshelf API. Optionally includes
the dashboard HTML and cover image.

Usage:
    storyforge publish                    # Publish content only
    storyforge publish --cover            # Include cover image
    storyforge publish --dashboard        # Include dashboard (default: on)
    storyforge publish --no-dashboard     # Skip dashboard
    storyforge publish --annotations      # Fetch and display reader annotations
    storyforge publish --dry-run          # Generate manifest without publishing
"""

import argparse
import json
import os
import subprocess
import sys

from storyforge.common import (
    detect_project_root, install_signal_handlers, log, read_yaml_field,
)


# ============================================================================
# Argument parsing
# ============================================================================

def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog='storyforge publish',
        description='Publish a book to the Bookshelf app via the API.',
    )
    parser.add_argument('--cover', action='store_true',
                        help='Include the cover image in the publish')
    parser.add_argument('--dashboard', action='store_true', default=True,
                        help='Include the dashboard HTML (default: on)')
    parser.add_argument('--no-dashboard', action='store_true',
                        help='Skip dashboard generation and inclusion')
    parser.add_argument('--annotations', action='store_true',
                        help='Fetch and display reader annotations after publishing')
    parser.add_argument('--dry-run', action='store_true',
                        help='Generate manifest and show what would be published')
    parser.add_argument('--skip-visualize', action='store_true',
                        help='Skip dashboard regeneration (use existing working/dashboard.html)')
    return parser.parse_args(argv)


# ============================================================================
# Dashboard regeneration
# ============================================================================

def _regenerate_dashboard(project_dir: str) -> bool:
    """Run storyforge visualize to regenerate dashboard.html.

    Returns True if the dashboard was successfully generated.
    """
    log('Regenerating dashboard...')
    try:
        # Find the storyforge runner
        runner = os.path.join(project_dir, 'storyforge')
        if not os.path.isfile(runner):
            # Fall back to module invocation
            from storyforge.common import get_plugin_dir
            runner = os.path.join(get_plugin_dir(), 'storyforge')

        subprocess.run(
            [runner, 'visualize'],
            cwd=project_dir,
            check=True,
            capture_output=True,
            text=True,
        )
        dashboard_path = os.path.join(project_dir, 'working', 'dashboard.html')
        if os.path.isfile(dashboard_path):
            log('Dashboard regenerated successfully.')
            return True
        log('Warning: visualize ran but dashboard.html not found.')
        return False
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        log(f'Warning: dashboard regeneration failed: {e}')
        return False


# ============================================================================
# Main
# ============================================================================

def main(argv=None):
    args = parse_args(argv or [])
    install_signal_handlers()
    project_dir = detect_project_root()

    include_dashboard = args.dashboard and not args.no_dashboard

    # Step 1: Regenerate dashboard if needed
    if include_dashboard and not args.skip_visualize and not args.dry_run:
        _regenerate_dashboard(project_dir)

    # Step 2: Generate manifest
    log('Generating publish manifest...')
    from storyforge.assembly import generate_publish_manifest
    try:
        manifest_path = generate_publish_manifest(
            project_dir,
            include_dashboard=include_dashboard,
            include_cover=args.cover,
        )
    except ValueError as e:
        log(f'Error: {e}')
        sys.exit(1)

    with open(manifest_path) as f:
        manifest = json.load(f)

    # Report manifest contents
    total_scenes = sum(len(ch['scenes']) for ch in manifest['chapters'])
    total_words = sum(
        s['word_count'] for ch in manifest['chapters'] for s in ch['scenes']
    )
    log(f'Manifest: {len(manifest["chapters"])} chapters, '
        f'{total_scenes} scenes, {total_words:,} words')
    if manifest.get('dashboard_html'):
        log(f'Dashboard: included ({len(manifest["dashboard_html"]):,} bytes)')
    if manifest.get('cover_base64'):
        log(f'Cover: included ({manifest["cover_extension"]})')

    if args.dry_run:
        log(f'Dry run — manifest written to {manifest_path}')
        log('Would publish to Bookshelf API. Exiting.')
        return

    # Step 3: Authenticate
    from storyforge.bookshelf import authenticate, check_env, publish
    env = check_env()

    log('Authenticating with Supabase...')
    try:
        token = authenticate(
            env['BOOKSHELF_SUPABASE_URL'],
            env['BOOKSHELF_SUPABASE_ANON_KEY'],
            env['BOOKSHELF_EMAIL'],
            env['BOOKSHELF_PASSWORD'],
        )
    except RuntimeError as e:
        log(f'Authentication failed: {e}')
        sys.exit(1)

    log('Authenticated successfully.')

    # Step 4: Publish
    log(f'Publishing "{manifest["title"]}" to Bookshelf...')
    try:
        result = publish(env['BOOKSHELF_URL'], token, manifest)
    except RuntimeError as e:
        log(f'Publish failed: {e}')
        sys.exit(1)

    # Step 5: Report results
    pub = result.get('published', {})
    log(f'Published successfully!')
    log(f'  Book ID: {result.get("book_id", "unknown")}')
    log(f'  Slug: {result.get("slug", "unknown")}')
    log(f'  Chapters: {pub.get("chapters", 0)}')
    log(f'  Scenes: {pub.get("scenes", 0)}')
    log(f'  Words: {pub.get("words", 0):,}')

    highlights = result.get('highlights', {})
    if highlights:
        parts = []
        if highlights.get('unchanged'):
            parts.append(f'{highlights["unchanged"]} unchanged')
        if highlights.get('reanchored'):
            parts.append(f'{highlights["reanchored"]} re-anchored')
        if highlights.get('orphaned'):
            parts.append(f'{highlights["orphaned"]} orphaned')
        if parts:
            log(f'  Highlights: {", ".join(parts)}')

    if result.get('cover_uploaded'):
        log('  Cover: uploaded')

    # Step 6: Fetch annotations if requested
    if args.annotations:
        _show_annotations(env, token, manifest['slug'])


def _show_annotations(env: dict, token: str, slug: str) -> None:
    """Fetch and display reader annotations."""
    from storyforge.bookshelf import get_annotations

    log(f'Fetching annotations for "{slug}"...')
    try:
        data = get_annotations(env['BOOKSHELF_URL'], token, slug)
    except RuntimeError as e:
        log(f'Warning: could not fetch annotations: {e}')
        return

    annotations = data.get('annotations', [])
    if not annotations:
        log('No annotations found.')
        return

    log(f'Found {len(annotations)} annotation(s):')
    for ann in annotations:
        chapter = ann.get('chapter', '?')
        color = ann.get('color', '')
        text = ann.get('highlighted_text', '')[:80]
        note = ann.get('note', '')
        prefix = f'  Ch.{chapter}'
        if color:
            prefix += f' [{color}]'
        line = f'{prefix}: "{text}"'
        if note:
            line += f' — {note}'
        log(line)
