"""storyforge assemble — Manuscript assembly and book production.

Reads chapter-map.csv and scene files, assembles chapters, generates
epub, PDF, or HTML output.

Usage:
    storyforge assemble                    # Full assembly + epub + web
    storyforge assemble --format epub      # Epub only
    storyforge assemble --format pdf       # PDF only
    storyforge assemble --format html      # HTML only
    storyforge assemble --format markdown  # Assembled markdown only
    storyforge assemble --all              # All available formats
    storyforge assemble --draft            # Quick assembly, no formatting
    storyforge assemble --dry-run          # Show what would be done
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import time

from storyforge.common import (
    detect_project_root, log, read_yaml_field, check_file_exists,
    get_plugin_dir, install_signal_handlers,
)
from storyforge.git import (
    create_branch, ensure_branch_pushed, create_draft_pr,
    update_pr_task, commit_and_push,
)


# ============================================================================
# Helpers
# ============================================================================

def _python_lib():
    """Return the Python library path for subprocess calls."""
    from pathlib import Path
    return str(Path(__file__).resolve().parent.parent)


def _run_assembly_cmd(*args) -> str:
    """Run a storyforge.assembly CLI command and return stdout."""
    env = os.environ.copy()
    env['PYTHONPATH'] = _python_lib()
    r = subprocess.run(
        [sys.executable, '-m', 'storyforge.assembly', *args],
        capture_output=True, text=True, env=env,
    )
    if r.returncode != 0:
        raise RuntimeError(f'Assembly command failed: {" ".join(args)}\n{r.stderr}')
    return r.stdout.strip()


def _get_chapter_scenes(ch_num: int, project_dir: str) -> list[str]:
    """Get scene IDs for a chapter."""
    output = _run_assembly_cmd('chapter-scenes', str(ch_num), project_dir)
    return [s.strip() for s in output.splitlines() if s.strip()]


def _read_production_field(project_dir: str, field: str) -> str:
    """Read a field from the production section of storyforge.yaml."""
    return read_yaml_field(f'production.{field}', project_dir)


def _check_pandoc() -> str:
    """Check if pandoc is available. Returns version or empty string."""
    try:
        r = subprocess.run(['pandoc', '--version'], capture_output=True, text=True)
        if r.returncode == 0:
            m = re.search(r'pandoc\s+([\d.]+)', r.stdout)
            return m.group(1) if m else 'unknown'
    except FileNotFoundError:
        pass
    return ''


def _word_count(filepath: str) -> int:
    with open(filepath) as f:
        return len(f.read().split())


# ============================================================================
# Argument parsing
# ============================================================================

VALID_FORMATS = {'epub', 'pdf', 'html', 'web', 'markdown', 'all'}


def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog='storyforge assemble',
        description='Assemble scenes into chapters and generate book output.',
    )
    parser.add_argument('--format', dest='formats', action='append', default=[],
                        help='Output format (repeatable, comma-separated ok): epub, pdf, html, web, markdown')
    parser.add_argument('--all', dest='all_formats', action='store_true',
                        help='Generate all available formats')
    parser.add_argument('--draft', action='store_true',
                        help='Quick assembly — markdown only, no formatting')
    parser.add_argument('--no-annotate', dest='annotate', action='store_false', default=True,
                        help='Disable web annotations')
    parser.add_argument('--annotate', action='store_true', default=True,
                        help=argparse.SUPPRESS)
    parser.add_argument('--interactive', '-i', action='store_true',
                        help='Run the review phase interactively')
    parser.add_argument('--dry-run', action='store_true',
                        help='Show what would be done without doing it')
    parser.add_argument('--skip-validation', action='store_true',
                        help='Skip epubcheck validation')
    parser.add_argument('--no-pr', action='store_true',
                        help='Skip PR creation')
    return parser.parse_args(argv)


def _resolve_formats(args) -> list[str]:
    """Resolve format flags into a list of format strings."""
    if args.draft:
        return ['markdown']
    if args.all_formats:
        return ['all']

    formats = []
    for f in args.formats:
        formats.extend(f.split(','))

    if not formats:
        formats = ['epub', 'web']

    for fmt in formats:
        if fmt not in VALID_FORMATS:
            print(f"ERROR: Unknown format '{fmt}'. Use: epub, pdf, html, web, markdown", file=sys.stderr)
            sys.exit(1)

    return formats


# ============================================================================
# Main
# ============================================================================

def main(argv=None):
    args = parse_args(argv or [])
    formats = _resolve_formats(args)

    install_signal_handlers()
    project_dir = detect_project_root()
    log(f'Project root: {project_dir}')

    plugin_dir = get_plugin_dir()
    python_lib = _python_lib()

    chapter_map = os.path.join(project_dir, 'reference', 'chapter-map.csv')
    manuscript_dir = os.path.join(project_dir, 'manuscript')
    output_dir = os.path.join(manuscript_dir, 'output')
    chapters_dir = os.path.join(manuscript_dir, 'chapters')
    log_dir = os.path.join(project_dir, 'working', 'logs')
    os.makedirs(log_dir, exist_ok=True)

    # Prerequisites
    check_file_exists(chapter_map, 'Chapter map (reference/chapter-map.csv)')

    total_chapters = int(_run_assembly_cmd('count-chapters', project_dir))
    if total_chapters == 0:
        log('ERROR: No chapters found in chapter-map.csv')
        log('Add chapters with scene mappings to reference/chapter-map.csv')
        sys.exit(1)

    # Verify scene files
    missing_scenes = 0
    for ch in range(1, total_chapters + 1):
        for scene_id in _get_chapter_scenes(ch, project_dir):
            if not os.path.isfile(os.path.join(project_dir, 'scenes', f'{scene_id}.md')):
                log(f'WARNING: Scene file missing: scenes/{scene_id}.md (chapter {ch})')
                missing_scenes += 1
    if missing_scenes > 0:
        log(f'WARNING: {missing_scenes} scene file(s) missing. Assembly will proceed with available scenes.')

    format_label = ','.join(formats)

    # Check pandoc
    needs_pandoc = any(f != 'markdown' for f in formats)
    pandoc_version = ''
    if needs_pandoc and not args.dry_run:
        pandoc_version = _check_pandoc()
        if not pandoc_version:
            if 'all' in formats:
                log('WARNING: pandoc not found — will generate markdown only')
                formats = ['markdown']
                format_label = 'markdown'
            else:
                log(f'ERROR: pandoc is required for {format_label} output but not found')
                log('Install: https://pandoc.org/installing.html')
                sys.exit(1)
        else:
            log(f'Found pandoc {pandoc_version}')

    # Read project info
    title = read_yaml_field('project.title', project_dir) or read_yaml_field('title', project_dir) or 'Unknown'
    genre = read_yaml_field('project.genre', project_dir) or read_yaml_field('genre', project_dir) or ''

    # ========================================================================
    # Dry-run mode
    # ========================================================================
    if args.dry_run:
        print('===== DRY RUN: assemble =====')
        print()
        print(f'Project: {title}')
        print(f'Chapters: {total_chapters}')
        print(f'Formats: {format_label}')
        print(f'Annotations: {args.annotate}')
        print()
        print('Chapter map:')
        for ch in range(1, total_chapters + 1):
            ch_title = _run_assembly_cmd('read-chapter-field', str(ch), project_dir, 'title')
            print(f'  Chapter {ch}: {ch_title}')
            for scene_id in _get_chapter_scenes(ch, project_dir):
                scene_file = os.path.join(project_dir, 'scenes', f'{scene_id}.md')
                if os.path.isfile(scene_file):
                    wc = _word_count(scene_file)
                    print(f'    - {scene_id} ({wc} words)')
                else:
                    print(f'    - {scene_id} (MISSING)')
        print()
        print(f'Output directory: {manuscript_dir}')
        print('Formats to generate:')
        for fmt in formats:
            if fmt == 'epub':
                print('  - epub3')
            elif fmt == 'pdf':
                print('  - PDF')
            elif fmt == 'html':
                print('  - HTML (single file)')
            elif fmt == 'web':
                print(f'  - Web book (multi-page, annotations: {args.annotate})')
            elif fmt == 'markdown':
                print('  - Markdown')
            elif fmt == 'all':
                print('  - Markdown')
                print('  - epub3')
                print('  - HTML (single file)')
                print(f'  - Web book (multi-page, annotations: {args.annotate})')
                print('  - PDF')
        print()
        print('===== END DRY RUN: assemble =====')
        return

    # ========================================================================
    # Session start
    # ========================================================================
    session_start = time.time()

    # Branch + PR setup
    create_branch('assemble', project_dir)
    ensure_branch_pushed(project_dir)

    pr_body = (
        f'## Assembly\n\n'
        f'**Project:** {title}\n'
        f'**Chapters:** {total_chapters}\n'
        f'**Formats:** {format_label}\n\n'
        f'### Tasks\n'
        f'- [ ] Assemble chapters\n'
        f'- [ ] Generate formats\n'
        f'- [ ] Review'
    )
    pr_number = ''
    if not args.no_pr:
        pr_number = create_draft_pr(f'Assemble: {title}', pr_body, project_dir, 'assembly')

    log('============================================')
    log('Starting Storyforge assembly')
    log(f'Project: {title}')
    log(f'Chapters: {total_chapters}')
    log(f'Formats: {format_label}')
    if args.draft:
        log('Mode: draft (quick assembly)')
    log('============================================')

    # Create output directories
    for d in [manuscript_dir, output_dir, chapters_dir,
              os.path.join(manuscript_dir, 'front-matter'),
              os.path.join(manuscript_dir, 'back-matter'),
              os.path.join(manuscript_dir, 'assets')]:
        os.makedirs(d, exist_ok=True)

    # ========================================================================
    # Phase 1: Assemble chapters
    # ========================================================================
    log(f'Assembling {total_chapters} chapters...')

    break_style = _read_production_field(project_dir, 'scene_break') or 'blank'
    total_words = 0

    for ch in range(1, total_chapters + 1):
        ch_title = _run_assembly_cmd('read-chapter-field', str(ch), project_dir, 'title')
        ch_file = os.path.join(chapters_dir, f'chapter-{ch:02d}.md')
        log(f'  Chapter {ch}: {ch_title}')

        env = os.environ.copy()
        env['PYTHONPATH'] = python_lib
        r = subprocess.run(
            [sys.executable, '-m', 'storyforge.assembly',
             'chapter', str(ch), project_dir, '--break-style', break_style],
            capture_output=True, text=True, env=env,
        )
        if r.returncode != 0:
            log(f'  WARNING: Failed to assemble chapter {ch}: {r.stderr}')
            continue

        with open(ch_file, 'w') as f:
            f.write(r.stdout)

        ch_words = len(r.stdout.split())
        total_words += ch_words
        log(f'    {ch_words} words -> {os.path.basename(ch_file)}')

    log(f'Chapter assembly complete: {total_words} words across {total_chapters} chapters')
    update_pr_task('Assemble chapters', project_dir, pr_number)

    # ========================================================================
    # Phase 2: Assemble full manuscript
    # ========================================================================
    manuscript_file = os.path.join(manuscript_dir, 'manuscript.md')
    log('Assembling full manuscript...')
    manuscript_words = _run_assembly_cmd('assemble', project_dir, manuscript_file)
    log(f'Full manuscript assembled: {manuscript_words} words -> manuscript.md')

    # Draft mode: stop here
    if args.draft:
        log('Draft mode — skipping format generation')
        log(f'Manuscript: {manuscript_file}')
        elapsed = int(time.time() - session_start)
        log(f'Assembly complete in {elapsed}s')
        return

    # ========================================================================
    # Phase 2.5: Generate cover if missing
    # ========================================================================
    env = os.environ.copy()
    env['PYTHONPATH'] = python_lib
    subprocess.run(
        [sys.executable, '-c',
         f'from storyforge.assembly import generate_cover_if_missing; '
         f'generate_cover_if_missing("{project_dir}", "{plugin_dir}")'],
        env=env, capture_output=True,
    )

    # ========================================================================
    # Phase 3: Generate output formats
    # ========================================================================
    title_slug = re.sub(r'[^a-z0-9-]', '', title.lower().replace(' ', '-'))

    # Import assembly functions for format generation
    env = os.environ.copy()
    env['PYTHONPATH'] = python_lib

    def _generate_format(fmt):
        if fmt == 'epub':
            epub_file = os.path.join(output_dir, f'{title_slug}.epub')
            subprocess.run(
                [sys.executable, '-c',
                 f'from storyforge.assembly import generate_epub; '
                 f'generate_epub("{project_dir}", "{manuscript_file}", "{epub_file}", "{plugin_dir}")'],
                env=env,
            )
            if not args.skip_validation and os.path.isfile(epub_file):
                subprocess.run(
                    [sys.executable, '-c',
                     f'from storyforge.assembly import validate_epub; validate_epub("{epub_file}")'],
                    env=env, capture_output=True,
                )
        elif fmt == 'html':
            html_file = os.path.join(output_dir, f'{title_slug}.html')
            subprocess.run(
                [sys.executable, '-c',
                 f'from storyforge.assembly import generate_html; '
                 f'generate_html("{project_dir}", "{manuscript_file}", "{html_file}", "{plugin_dir}")'],
                env=env,
            )
        elif fmt == 'pdf':
            pdf_file = os.path.join(output_dir, f'{title_slug}.pdf')
            subprocess.run(
                [sys.executable, '-c',
                 f'from storyforge.assembly import generate_pdf; '
                 f'generate_pdf("{project_dir}", "{manuscript_file}", "{pdf_file}", "{plugin_dir}")'],
                env=env,
            )
        elif fmt == 'web':
            subprocess.run(
                [sys.executable, '-c',
                 f'from storyforge.assembly import generate_web_book; '
                 f'generate_web_book("{project_dir}", "{plugin_dir}", {args.annotate})'],
                env=env,
            )
        elif fmt == 'markdown':
            log(f'Markdown manuscript already at: {manuscript_file}')

    for fmt in formats:
        if fmt == 'all':
            _generate_format('markdown')
            if pandoc_version:
                _generate_format('epub')
                _generate_format('html')
                _generate_format('web')
                try:
                    _generate_format('pdf')
                except Exception:
                    log('WARNING: PDF generation failed (non-fatal)')
        else:
            _generate_format(fmt)

    # ========================================================================
    # Update storyforge.yaml
    # ========================================================================
    from datetime import date
    today = date.today().isoformat()
    yaml_path = os.path.join(project_dir, 'storyforge.yaml')
    if os.path.isfile(yaml_path):
        with open(yaml_path) as f:
            content = f.read()
        # Update chapter_map and manuscript artifacts
        for artifact in ('chapter_map', 'manuscript'):
            pattern = rf'({artifact}:.*?)(exists: false)'
            content = re.sub(pattern, r'\1exists: true', content, flags=re.DOTALL)
            pattern = rf'({artifact}:.*?updated:).*'
            content = re.sub(pattern, rf'\1 "{today}"', content, flags=re.DOTALL)
        with open(yaml_path, 'w') as f:
            f.write(content)

    update_pr_task('Generate formats', project_dir, pr_number)

    # ========================================================================
    # Session complete
    # ========================================================================
    elapsed = int(time.time() - session_start)
    mins, secs = divmod(elapsed, 60)

    log('============================================')
    log('Assembly complete!')
    log(f'Chapters: {total_chapters}')
    log(f'Total words: {manuscript_words}')
    log(f'Output: {output_dir}/')

    if os.path.isdir(output_dir):
        for f in sorted(os.listdir(output_dir)):
            fp = os.path.join(output_dir, f)
            if os.path.isfile(fp):
                size = os.path.getsize(fp)
                if size > 1024 * 1024:
                    size_str = f'{size / (1024*1024):.1f}M'
                elif size > 1024:
                    size_str = f'{size / 1024:.0f}K'
                else:
                    size_str = f'{size}B'
                log(f'  {f} ({size_str})')

    log(f'Time: {mins}m{secs}s')
    log('============================================')

    # Git commit
    commit_and_push(
        project_dir,
        f'Assemble: {title} ({format_label})',
        ['manuscript/', 'storyforge.yaml', 'working/logs/', 'working/costs/'],
    )
