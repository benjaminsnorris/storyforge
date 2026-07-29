"""storyforge publish -- Publish a book to the Bookshelf app via API.

Generates a publish manifest from the scene files and chapter map, authenticates
with Supabase, uploads any image bytes the server does not already hold, then
PUTs the metadata-only manifest to the Bookshelf API.

Images (the cover and any interior illustrations) are content-addressed. They
are declared as manifest metadata and their bytes go straight to storage via
signed upload URLs, so a re-publish with unchanged art transfers nothing. See
`storyforge.bookshelf.sync_assets`.

The cover is always published as a `role: 'cover'` asset. It is not optional for
an illustrated book: Bookshelf derives the book's cover image from that entry,
so a manifest declaring assets without one would clear the live cover.

Usage:
    storyforge publish                    # Publish content, cover, and art
    storyforge publish --no-cover         # Omit the cover asset (no assets only)
    storyforge publish --dashboard        # Include dashboard (default: on)
    storyforge publish --no-dashboard     # Skip dashboard
    storyforge publish --annotations      # Fetch and display reader annotations
    storyforge publish --dry-run          # Report what would publish and upload
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
                        help='Deprecated no-op — the cover is always published '
                             'as an asset')
    parser.add_argument('--no-cover', action='store_true',
                        help='Omit the cover asset. Only valid for a book with '
                             'no illustrations; publishing other assets without '
                             'a cover is refused because it would clear the '
                             "live book's cover image")
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
    include_cover = not args.no_cover
    if args.cover:
        log('Note: --cover is a no-op — the cover is always published as an '
            'asset now. Pass --no-cover to omit it.')

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
            include_cover=include_cover,
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

    # Second line of defence behind generate_publish_manifest's own check.
    #
    # It does NOT protect a hand-edited working/publish-manifest.json — that file
    # is overwritten a few lines above, so an edit to it is discarded by
    # regeneration, not caught here. What this covers is a manifest that reached
    # this point without going through the generator's check: a bypassed or
    # changed generator, which is exactly what the test exercises. Cheap
    # insurance on the one operation in this command that can destroy live data.
    #
    # Runs before the dry-run return: an author checking their publish should see
    # this, not discover it on the real run.
    from storyforge.assembly import read_asset_sources, require_cover_asset
    assets = manifest.get('assets') or []
    try:
        require_cover_asset(manifest)
    except ValueError as e:
        log(f'Error: {e}')
        sys.exit(1)

    sources = read_asset_sources(project_dir) if assets else {}
    if assets and not sources:
        # generate_publish_manifest writes the sidecar in the same pass as the
        # manifest, so an empty one means the sidecar was deleted or the
        # generator was bypassed. Named now rather than surfacing as an opaque
        # per-digest failure later.
        log('WARNING: the manifest declares assets but '
            'working/publish-asset-sources.json maps no digests to files. '
            'Re-run publish so the manifest and its source map are generated '
            'together.')

    if args.dry_run:
        log(f'Dry run — manifest written to {manifest_path}')
        if assets:
            _report_asset_plan(assets, sources)
        log('Would publish to Bookshelf API. Nothing uploaded. Exiting.')
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

    # Step 4: Upload asset bytes.
    #
    # Before the manifest, not after: the publish route refuses a manifest whose
    # declared bytes are not in the bucket (`assets_missing_bytes`), and it
    # refuses it at a phase that runs before chapters are written — so a book
    # blocked here is intact, never half-published.
    asset_sync = None
    if assets:
        from storyforge.bookshelf import sync_assets
        log(f'Syncing {len(assets)} asset(s) with Bookshelf storage...')
        try:
            asset_sync = sync_assets(
                env['BOOKSHELF_URL'], token, manifest['slug'], assets, sources,
            )
        except Exception as e:
            # Broader than RuntimeError: a socket that drops mid-transfer can
            # surface as a bare OSError subclass, and a traceback here would
            # bury the one thing the author needs to know — that nothing was
            # published and the live book is untouched.
            log(f'Asset sync failed: {e}')
            log('The manifest was not sent — the live book is unchanged.')
            sys.exit(1)
        log(f'Assets: {asset_sync["uploaded"]} uploaded '
            f'({asset_sync["bytes_uploaded"]:,} bytes), '
            f'{asset_sync["unchanged"]} already present')

    # Step 5: Publish
    log(f'Publishing "{manifest["title"]}" to Bookshelf...')
    try:
        result = publish(env['BOOKSHELF_URL'], token, manifest)
    except RuntimeError as e:
        log(f'Publish failed: {e}')
        _explain_publish_failure(str(e))
        sys.exit(1)

    # Step 6: Report results
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

    if asset_sync:
        log(f'  Assets: {asset_sync["declared"]} declared, '
            f'{asset_sync["uploaded"]} uploaded, '
            f'{asset_sync["unchanged"]} unchanged '
            f'({asset_sync["bytes_uploaded"]:,} bytes transferred)')

    # Step 7: Fetch annotations if requested
    if args.annotations:
        _show_annotations(env, token, manifest['slug'])


def _report_asset_plan(assets: list, sources: dict) -> None:
    """Dry-run asset report: what would upload, and what could not.

    Cannot say which digests the server already holds — that needs the
    authenticated digest diff, which a dry run deliberately does not perform.
    What it can do is check every declared asset against its local file, which
    is where the failures actually are.
    """
    from storyforge.illustrations import sha256_of

    by_role: dict[str, int] = {}
    for asset in assets:
        role = asset.get('role', 'unknown')
        by_role[role] = by_role.get(role, 0) + 1
    breakdown = ', '.join(f'{n} {role}' for role, n in sorted(by_role.items()))
    log(f'Assets: {len(assets)} declared ({breakdown}). Would negotiate '
        f'digests and upload only the bytes Bookshelf is missing.')

    problems = 0
    total_bytes = 0
    for asset in assets:
        digest = asset.get('sha256', '')
        local = sources.get(digest)
        label = f'{asset.get("key")} ({digest[:12]}…)'
        if not local:
            log(f'  ERROR: {label} has no local file recorded — re-run '
                f'`storyforge illustrate --ingest`')
            problems += 1
            continue
        if not os.path.isfile(local):
            log(f'  ERROR: {label} file is missing: {local}')
            problems += 1
            continue
        try:
            actual = sha256_of(local)
        except OSError as e:
            log(f'  ERROR: {label} cannot be read: {e}')
            problems += 1
            continue
        if actual != digest:
            log(f'  ERROR: {label} has drifted — {local} now hashes to '
                f'{actual[:12]}…; re-ingest to record it')
            problems += 1
            continue
        total_bytes += os.path.getsize(local)

    if problems:
        log(f'  {problems} asset(s) would block the publish. Nothing uploaded '
            f'(dry run).')
    else:
        log(f'  All {len(assets)} asset file(s) resolve and match their '
            f'digests; up to {total_bytes:,} bytes would transfer on a first '
            f'publish. Nothing uploaded (dry run).')


def _explain_publish_failure(message: str) -> None:
    """Add an actionable next step to the server's own error phase."""
    if 'assets_missing_bytes' in message:
        log('Bookshelf has metadata for assets whose bytes are not in storage. '
            'The upload step ran but did not cover them — re-run publish; if it '
            'repeats, check that every plan row\'s sha256 matches its file '
            '(`storyforge cleanup`).')
    elif 'assets_digest_mismatch' in message:
        log('Bookshelf re-hashed the uploaded bytes and got a different digest '
            'than the manifest declared. The file changed between ingest and '
            'publish. Re-run `storyforge illustrate --ingest` to record the '
            'current digest, then publish again.')
    elif 'assets_validate' in message:
        log('Bookshelf rejected the assets array itself. The likeliest cause is '
            'more than 200 assets: the publish route validates the manifest\'s '
            'array against the same 200 cap as the upload endpoint. Split the '
            'book or retire illustrations with status=superseded.')
    elif 'assets_legacy_cover' in message:
        log('The manifest sent both a cover asset and the deprecated '
            'cover_base64 field. Regenerate the manifest with the current '
            'plugin version.')


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
