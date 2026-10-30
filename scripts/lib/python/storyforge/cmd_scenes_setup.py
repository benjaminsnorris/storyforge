"""storyforge scenes-setup — Prepare manuscript into formatted scene files.

Handles three input scenarios:
  --rename           Rename existing scene files to proper slugs
  --split-chapters   Split chapter files into individual scenes
  --split-manuscript Split a single manuscript file into scenes

Usage:
    storyforge scenes-setup --rename
    storyforge scenes-setup --split-chapters --source chapters/
    storyforge scenes-setup --split-manuscript --source manuscript.md
    storyforge scenes-setup --split-chapters --dry-run
"""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime

from storyforge.common import (
    detect_project_root, log, read_yaml_field, select_model,
    install_signal_handlers, build_shared_context,
)
from storyforge.git import (
    create_branch, ensure_branch_pushed, create_draft_pr,
    commit_and_push, _git,
)
from storyforge.api import (
    invoke_to_file, extract_text, extract_usage, calculate_cost_from_usage,
    submit_batch, poll_batch, download_batch_results, build_batch_request,
    is_truncated, stop_problem,
)
from storyforge.costs import (
    estimate_cost, check_threshold, print_summary, log_operation,
)
from storyforge.scenes import (
    generate_slug, unique_slug, scene_id_slug, is_break_marker, parse_scene_boundaries,
    build_boundary_prompt, scenes_header, intent_header,
    _title_from_file,
)
from storyforge.csv_cli import get_field, get_column, append_row


# A part (or book, or volume) heading: "Part One", "PART II",
# "# Part 3: The Lighthouse", "BOOK FIRST", "VOL. II.". The whole line must be the heading (an ordinal, then at most a
# separator and a short title), so prose such as "Part one of the plan was
# simple." never matches.
_PART_HEADING_RE = re.compile(
    r'^(?:#{1,2}\s+)?(?:part|book|volume|vol\.)\s+(?:[0-9]+|[ivxlc]+|one|two|three|four|five|'
    r'six|seven|eight|nine|ten|first|second|third|fourth|fifth|sixth|seventh|'
    r'eighth|ninth|tenth)\s*(?:[:.\-—–]\s*[^.!?]{0,60})?$',
    re.IGNORECASE,
)


def _is_part_heading(line):
    stripped = line.strip()
    return len(stripped) <= 80 and bool(_PART_HEADING_RE.match(stripped))


def _natural_key(path):
    """Sort key that orders chapter-2 before chapter-10."""
    name = os.path.basename(path).lower()
    return [int(t) if t.isdigit() else t for t in re.split(r'(\d+)', name)]


def _row_for_header(csv_path, values):
    """Build a pipe-delimited row in the column order of csv_path's header.

    Columns absent from values are left empty, so the row stays aligned
    whichever schema version the project's CSV was created with.
    """
    with open(csv_path, encoding='utf-8') as f:
        header = f.readline().rstrip('\r\n').split('|')
    return '|'.join(str(values.get(col, '')) for col in header)


def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog='storyforge scenes-setup',
        description='Prepare a manuscript into properly formatted scene files.',
    )

    mode_group = parser.add_argument_group('modes (exactly one required)')
    mode_group.add_argument('--rename', action='store_true',
                            help='Rename existing scene files to slugs')
    mode_group.add_argument('--split-chapters', action='store_true',
                            help='Split chapter files into scenes')
    mode_group.add_argument('--split-manuscript', action='store_true',
                            help='Split a single manuscript file')

    parser.add_argument('--source', type=str, default='',
                        help='Source directory (for chapters) or file (for manuscript)')
    parser.add_argument('--direct', action='store_true',
                        help='Use direct API calls instead of batch (default: batch)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Show what would happen without making changes')
    parser.add_argument('--yes', action='store_true',
                        help='Skip interactive confirmation of splits')
    parser.add_argument('--parallel', type=int, default=None,
                        help='Workers for Claude calls (default: 6)')

    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv or [])
    session_start = datetime.now().strftime('%Y-%m-%dT%H:%M:%S')

    # Validate mode
    modes = sum([args.rename, args.split_chapters, args.split_manuscript])
    if modes == 0:
        print('ERROR: Must specify one of --rename, --split-chapters, or --split-manuscript',
              file=sys.stderr)
        sys.exit(1)
    if modes > 1:
        print('ERROR: Only one mode may be specified', file=sys.stderr)
        sys.exit(1)

    install_signal_handlers()
    project_dir = detect_project_root()
    log(f'Project root: {project_dir}')

    # API key check
    if not args.dry_run and not os.environ.get('ANTHROPIC_API_KEY'):
        log('ERROR: ANTHROPIC_API_KEY is required. Set it with: export ANTHROPIC_API_KEY=your-key')
        sys.exit(1)

    title = read_yaml_field('project.title', project_dir) or read_yaml_field('title', project_dir) or 'Unknown'
    parallel = args.parallel or int(os.environ.get('STORYFORGE_SCENES_PARALLEL', '6'))
    setup_mode = 'direct' if args.direct else os.environ.get('STORYFORGE_SETUP_MODE', 'batch')

    # Paths
    scenes_dir = os.path.join(project_dir, 'scenes')
    metadata_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
    intent_csv = os.path.join(project_dir, 'reference', 'scene-intent.csv')
    chapter_map_csv = os.path.join(project_dir, 'reference', 'chapter-map.csv')
    log_dir = os.path.join(project_dir, 'working', 'logs')
    work_dir = os.path.join(project_dir, 'working', 'scenes-setup')

    for d in [log_dir, work_dir, scenes_dir, os.path.join(project_dir, 'reference')]:
        os.makedirs(d, exist_ok=True)

    # Move old CSV location if needed
    old_intent = os.path.join(project_dir, 'scenes', 'intent.csv')
    new_intent = os.path.join(project_dir, 'reference', 'scene-intent.csv')
    if os.path.isfile(old_intent) and not os.path.isfile(new_intent):
        os.rename(old_intent, new_intent)
        log('Moved scenes/intent.csv -> reference/scene-intent.csv')

    model = select_model('evaluation')
    system = build_shared_context(project_dir, model=model)

    # Track used slugs
    used_slugs = set()

    # Part number per temp chapter file, filled by split-manuscript from the
    # manuscript's own part headings. A book without parts leaves `part`
    # empty rather than having parts invented for it.
    chapter_parts = {}

    # ==================================================================
    # Shared utilities
    # ==================================================================

    def ensure_metadata_csv():
        if not os.path.isfile(metadata_csv):
            with open(metadata_csv, 'w') as f:
                f.write(scenes_header() + '\n')
            log('Created reference/scenes.csv')

    def ensure_intent_csv():
        if not os.path.isfile(intent_csv):
            with open(intent_csv, 'w') as f:
                f.write(intent_header() + '\n')
            log('Created reference/scene-intent.csv')

    def count_words(text):
        return len(text.split())

    def detect_explicit_breaks(text):
        """Detect scene break markers. Returns list of line numbers."""
        breaks = []
        blank_count = 0
        prev_blank = False

        lines = text.splitlines()
        for line_num, line in enumerate(lines, 1):
            stripped = line.strip()
            # A marker follows a blank line; "---" or "___" directly under a
            # line of text is a Markdown setext heading underline instead.
            if is_break_marker(stripped) and (line_num == 1 or not lines[line_num - 2].strip()):
                if line_num > 1:
                    breaks.append(line_num)
                blank_count = 0
                prev_blank = False
                continue
            if not stripped:
                blank_count += 1
                if blank_count >= 3 and not prev_blank:
                    breaks.append(line_num)
                    prev_blank = True
            else:
                blank_count = 0
                prev_blank = False

        return breaks

    def find_content_start(text, after_line):
        """Find first non-empty, non-marker line after a given line number."""
        for line_num, line in enumerate(text.splitlines(), 1):
            if line_num <= after_line:
                continue
            stripped = line.strip()
            if stripped and stripped not in ('', '***', '---', '# # #', '* * *'):
                return line_num
        return after_line

    def build_splits_from_markers(chapter_text, break_lines):
        """Build split info from explicit break markers.

        Markers give boundaries but no titles. Titles are left empty for
        extraction to write (it only fills empty fields), rather than filled
        with a chapter heading or the first 60 characters of prose.
        """
        splits = [{'line': 1, 'title': '', 'reason': 'Chapter opening'}]
        for brk in break_lines:
            splits.append({
                'line': find_content_start(chapter_text, brk),
                'title': '',
                'reason': 'Explicit scene break marker',
            })
        return splits

    def confirm_splits(chapter_name, chapter_text, splits):
        """Display proposed splits and get confirmation. Returns True to accept."""
        lines_list = chapter_text.splitlines()
        total_lines = len(lines_list)
        total_words = count_words(chapter_text)

        print(f'\n{chapter_name} ({total_words} words)')
        print('  Proposed splits:')

        for s_idx, split in enumerate(splits):
            start_line = split['line']
            if s_idx + 1 < len(splits):
                end_line = splits[s_idx + 1]['line'] - 1
            else:
                end_line = total_lines
            seg_text = '\n'.join(lines_list[start_line - 1:end_line])
            seg_words = count_words(seg_text)
            opening = next((l.strip() for l in seg_text.splitlines() if l.strip()), '')
            label = split.get('slug') or split.get('title') or f'{opening[:60]}...'
            print(f'    Scene {s_idx + 1}: "{label}" '
                  f'(lines {start_line}-{end_line}, ~{seg_words} words) -- {split["reason"]}')

        if args.yes:
            print('  Auto-accepting (--yes)')
            return True

        try:
            answer = input('  Accept? [Y/n/edit] ').strip()
        except (EOFError, KeyboardInterrupt):
            answer = 'y'

        if answer.lower() in ('n',):
            return False
        if answer.lower() in ('edit', 'e'):
            try:
                new_lines_str = input('  Enter new line numbers (space-separated): ').strip()
            except (EOFError, KeyboardInterrupt):
                new_lines_str = ''
            if new_lines_str:
                new_splits = []
                for ln_str in new_lines_str.split():
                    if ln_str.isdigit():
                        ln = int(ln_str)
                        seg_title = ''
                        if ln <= len(lines_list):
                            seg_title = lines_list[ln - 1].strip()[:60]
                        if not seg_title:
                            seg_title = f'Scene {len(new_splits) + 1}'
                        new_splits.append({
                            'line': ln,
                            'title': seg_title,
                            'reason': 'Manual edit',
                        })
                if new_splits:
                    splits.clear()
                    splits.extend(new_splits)
        return True

    def write_scene_files(chapter_text, chapter_num, part_num, seq_start, splits):
        """Write scene files from splits. Returns list of written scene IDs."""
        lines_list = chapter_text.splitlines()
        total_lines = len(lines_list)

        ensure_metadata_csv()
        ensure_intent_csv()

        written_ids = []

        for s_idx, split in enumerate(splits):
            start_line = split['line']
            if s_idx + 1 < len(splits):
                end_line = splits[s_idx + 1]['line'] - 1
            else:
                end_line = total_lines

            # Extract scene text, skip break markers
            seg_lines = lines_list[start_line - 1:end_line]
            cleaned = []
            for ln in seg_lines:
                stripped = ln.strip()
                if is_break_marker(stripped):
                    continue
                cleaned.append(ln)
            # Trim leading blank lines
            while cleaned and not cleaned[0].strip():
                cleaned.pop(0)
            scene_text = '\n'.join(cleaned)

            # Scene id: a slug of the scene's event, never its position. When
            # Claude supplied no name, fall back to the scene's opening words.
            stitle = re.sub(r'^#+\s*', '', split.get('title', ''))
            slug = scene_id_slug(split.get('slug', ''))
            if not slug:
                opening = next((l for l in cleaned if l.strip()
                                and not re.match(r'^#', l.strip())), '')
                slug = scene_id_slug(opening) or 'scene'
                log(f'  WARNING: no scene name from Claude; using "{slug}". Rename it '
                    f'to a 3-5 word slug of the scene\'s event now, before anything '
                    f'references it: scene ids are permanent once referenced')
            slug = unique_slug(slug, used_slugs)

            scene_file = os.path.join(scenes_dir, f'{slug}.md')

            if not args.dry_run:
                with open(scene_file, 'w') as f:
                    f.write(scene_text + '\n')

                seq_num = seq_start + s_idx
                word_count = count_words(scene_text)
                append_row(metadata_csv, _row_for_header(metadata_csv, {
                    'id': slug, 'seq': seq_num, 'title': stitle,
                    'part': part_num, 'word_count': word_count,
                }))
                append_row(intent_csv, _row_for_header(intent_csv, {'id': slug}))

                log(f'  Created scenes/{slug}.md ({word_count} words)')
            else:
                log(f'  [DRY RUN] Would create scenes/{slug}.md')

            written_ids.append(slug)

        return written_ids

    def chapter_prompt(chapter_text):
        """Boundary prompt for a chapter; marker boundaries are fixed, so the
        model only names those scenes."""
        breaks = detect_explicit_breaks(chapter_text)
        fixed = ([s['line'] for s in build_splits_from_markers(chapter_text, breaks)]
                 if breaks else None)
        return build_boundary_prompt(chapter_text, fixed)

    # Chapters whose scene detection failed (errored, refused or cut off):
    # left unsplit, since a guess would write wrong scene files with
    # permanent ids. The run names them and exits 1 after committing the rest.
    detect_failed: dict[str, str] = {}

    def report_failed_detection():
        if not detect_failed:
            return
        log(f'ERROR: scene detection failed for {len(detect_failed)} chapter(s); '
            f'they were not split:')
        for ch_name, why in detect_failed.items():
            log(f'  {ch_name}: {why}')
        log('Re-run scenes-setup for those chapters.')
        sys.exit(1)

    def claude_detect_scenes(chapter_text, chapter_id):
        """Use direct API to detect scene boundaries and name the scenes."""
        prompt = chapter_prompt(chapter_text)
        lf = os.path.join(log_dir, f'scenes-setup-detect-{chapter_id}.json')

        response_data = invoke_to_file(prompt, model, lf, max_tokens=4096, system=system)
        response = extract_text(response_data)

        # Log usage
        usage = extract_usage(response_data)
        cost = calculate_cost_from_usage(usage, model)
        log_operation(project_dir, 'scene-detect', model,
                      usage['input_tokens'], usage['output_tokens'],
                      cost, target=chapter_id,
                      cache_read=usage.get('cache_read', 0),
                      cache_create=usage.get('cache_create', 0))

        # A cut-off reply names only some boundaries: splitting on it would
        # write wrong scene files. (A refusal raises in invoke_to_file.)
        if is_truncated(response_data):
            raise RuntimeError(stop_problem(response_data))
        return response

    # ==================================================================
    # Mode 1: Rename existing scenes
    # ==================================================================

    def do_rename():
        log('============================================')
        log('Mode: Rename existing scene files to slugs')
        log('============================================')

        ensure_metadata_csv()
        ensure_intent_csv()

        # Collect scene files
        scene_files = sorted(
            os.path.join(scenes_dir, f)
            for f in os.listdir(scenes_dir)
            if f.endswith('.md') and os.path.isfile(os.path.join(scenes_dir, f))
        )

        if not scene_files:
            log(f'ERROR: No scene files found in {scenes_dir}')
            sys.exit(1)

        log(f'Found {len(scene_files)} scene files')

        # Build rename plan
        renames = []  # list of (old_id, new_id)

        for scene_file in scene_files:
            old_id = os.path.basename(scene_file)[:-3]

            # Try to get title from metadata CSV first
            stitle = get_field(metadata_csv, old_id, 'title') or ''
            if not stitle:
                stitle = _title_from_file(scene_file)

            new_slug = generate_slug(stitle) if stitle else generate_slug(old_id)
            if not new_slug:
                new_slug = old_id
            new_slug = unique_slug(new_slug, used_slugs)

            if old_id != new_slug:
                renames.append((old_id, new_slug))
            # slug already tracked in used_slugs by unique_slug

        if not renames:
            log('No files need renaming. All files already have slug names.')
            sys.exit(0)

        # Show plan
        log('')
        log('Rename plan:')
        for old_id, new_id in renames:
            log(f'  {old_id}.md -> {new_id}.md')
        log('')

        if args.dry_run:
            log('DRY RUN -- no changes made')
            sys.exit(0)

        # Execute renames
        for old_id, new_id in renames:
            old_rel = f'scenes/{old_id}.md'
            new_rel = f'scenes/{new_id}.md'

            # Check if tracked by git
            r = _git(project_dir, 'ls-files', '--error-unmatch', old_rel, check=False)
            if r.returncode == 0:
                _git(project_dir, 'mv', old_rel, new_rel, check=False)
            else:
                os.rename(
                    os.path.join(project_dir, old_rel),
                    os.path.join(project_dir, new_rel),
                )
            log(f'  Renamed {old_id} -> {new_id}')

        # Update metadata CSV -- replace old IDs with new IDs
        def _replace_ids_in_csv(csv_path, old_id, new_id):
            if not os.path.isfile(csv_path):
                return
            with open(csv_path) as f:
                content = f.read()
            content = re.sub(rf'^{re.escape(old_id)}\|', f'{new_id}|', content, flags=re.MULTILINE)
            with open(csv_path, 'w') as f:
                f.write(content)

        for old_id, new_id in renames:
            _replace_ids_in_csv(metadata_csv, old_id, new_id)
            _replace_ids_in_csv(intent_csv, old_id, new_id)

        # Update chapter-map.csv if it exists
        if os.path.isfile(chapter_map_csv):
            with open(chapter_map_csv) as f:
                content = f.read()
            for old_id, new_id in renames:
                content = content.replace(old_id, new_id)
            with open(chapter_map_csv, 'w') as f:
                f.write(content)
            log('Updated reference/chapter-map.csv')

        log(f'\nRenamed {len(renames)} scene files')
        return len(renames)

    # ==================================================================
    # Mode 2: Split chapters into scenes
    # ==================================================================

    def do_split_chapters():
        log('============================================')
        log('Mode: Split chapter files into scenes')
        log('============================================')

        # Determine source directory
        src_dir = args.source
        if src_dir:
            if not os.path.isabs(src_dir):
                src_dir = os.path.join(project_dir, src_dir)
        else:
            for candidate in ['chapters', 'manuscript']:
                d = os.path.join(project_dir, candidate)
                if os.path.isdir(d):
                    src_dir = d
                    break
            if not src_dir:
                log('ERROR: No chapter directory found. Use --source to specify.')
                sys.exit(1)

        if not os.path.isdir(src_dir):
            log(f'ERROR: Source directory does not exist: {src_dir}')
            sys.exit(1)

        log(f'Source directory: {src_dir}')

        # Collect chapter files (sorted)
        chapter_files = sorted(
            (os.path.join(src_dir, f)
             for f in os.listdir(src_dir)
             if f.endswith('.md') or f.endswith('.txt')),
            key=_natural_key,
        )
        chapter_files = [f for f in chapter_files if os.path.isfile(f)]

        if not chapter_files:
            log(f'ERROR: No chapter files found in {src_dir}')
            sys.exit(1)

        log(f'Found {len(chapter_files)} chapter files')

        ensure_metadata_csv()
        ensure_intent_csv()

        # Find next available seq number
        max_seq = 0
        for val in get_column(metadata_csv, 'seq'):
            val = val.strip()
            if val.isdigit():
                max_seq = max(max_seq, int(val))

        # Separate chapters with explicit markers vs needing Claude
        marker_chapters = []
        claude_chapters = []

        if not args.dry_run:
            for cf in chapter_files:
                with open(cf) as f:
                    text = f.read()
                breaks = detect_explicit_breaks(text)
                if breaks:
                    marker_chapters.append(cf)
                else:
                    claude_chapters.append(cf)
            log(f'{len(marker_chapters)} chapters have explicit markers (Claude names '
                f'their scenes), {len(claude_chapters)} need Claude detection')
            # Every chapter needs Claude: scene ids are slugs of each scene's
            # event, which markers alone cannot supply.
            claude_chapters = list(chapter_files)

        # Process chapters needing Claude detection
        if not args.dry_run and claude_chapters:
            claude_total = len(claude_chapters)

            if setup_mode == 'batch':
                # Batch mode: submit all chapters as a single batch
                log(f'Submitting {claude_total} chapters to Batch API...')

                batch_file = os.path.join(work_dir, '.batch-input.jsonl')
                with open(batch_file, 'w') as bf:
                    for cf in claude_chapters:
                        ch_name = os.path.splitext(os.path.basename(cf))[0]
                        with open(cf) as fh:
                            chapter_text = fh.read()
                        prompt = chapter_prompt(chapter_text)
                        request = build_batch_request(ch_name, prompt, model,
                                                      max_tokens=4096, system=system)
                        bf.write(json.dumps(request) + '\n')

                batch_id = submit_batch(batch_file)
                if not batch_id:
                    log('ERROR: Batch submission failed. Falling back to direct mode.')
                    setup_mode_actual = 'direct'
                else:
                    log(f'  Batch submitted: {batch_id}')
                    log('  Polling for results...')
                    results_url = poll_batch(batch_id, log_fn=log)

                    log('  Downloading results...')
                    succeeded = download_batch_results(results_url, work_dir, log_dir)

                    # Move results into detect files
                    for cf in claude_chapters:
                        ch_name = os.path.splitext(os.path.basename(cf))[0]
                        txt_file = os.path.join(log_dir, f'{ch_name}.txt')
                        json_file = os.path.join(log_dir, f'{ch_name}.json')
                        status_file = os.path.join(work_dir, f'.status-{ch_name}')

                        if os.path.isfile(status_file):
                            with open(status_file) as f:
                                status = f.read().strip()
                            if status == 'ok' and os.path.isfile(txt_file):
                                detect_file = os.path.join(work_dir, f'.detect-{ch_name}.txt')
                                with open(txt_file) as src, open(detect_file, 'w') as dst:
                                    dst.write(src.read())
                            else:
                                detect_failed[ch_name] = ('the batch reply errored, was '
                                                          'refused or was cut off')
                            if os.path.isfile(json_file):
                                with open(json_file) as jf:
                                    resp_data = json.load(jf)
                                usage = extract_usage(resp_data)
                                cost = calculate_cost_from_usage(usage, model)
                                log_operation(project_dir, 'scene-detect', model,
                                              usage['input_tokens'], usage['output_tokens'],
                                              cost, target=ch_name,
                                              cache_read=usage.get('cache_read', 0),
                                              cache_create=usage.get('cache_create', 0))
                        else:
                            log(f'  WARNING: Batch item failed for {ch_name}')
                            detect_failed[ch_name] = 'no batch result'

                        # Cleanup temp files
                        for path in [status_file, txt_file, json_file]:
                            try:
                                os.remove(path)
                            except FileNotFoundError:
                                pass

                    os.remove(batch_file)
                    log('  Batch processing complete')
                    setup_mode_actual = 'batch'

            if setup_mode == 'direct' or (setup_mode == 'batch' and not batch_id):
                # Direct mode: parallel API calls
                log(f'Processing {claude_total} chapters via direct API (parallel={parallel})...')

                from storyforge.runner import run_parallel

                def _detect_worker(cf):
                    ch_name = os.path.splitext(os.path.basename(cf))[0]
                    with open(cf) as fh:
                        chapter_text = fh.read()
                    log(f'  Launching scene detection for {ch_name}...')
                    response = claude_detect_scenes(chapter_text, ch_name)
                    detect_file = os.path.join(work_dir, f'.detect-{ch_name}.txt')
                    with open(detect_file, 'w') as df:
                        df.write(response)
                    return ch_name

                results = run_parallel(claude_chapters, _detect_worker,
                                       max_workers=parallel, label='chapter')
                for cf, r in results.items():
                    if isinstance(r, Exception):
                        detect_failed[os.path.splitext(os.path.basename(cf))[0]] = str(r)

        # Now process all chapters sequentially
        chapter_num = 0
        total_new_scenes = 0

        for chapter_file in chapter_files:
            chapter_num += 1
            part_num = chapter_parts.get(os.path.basename(chapter_file), '')
            seq_start = max_seq + total_new_scenes + 1

            ch_name = os.path.splitext(os.path.basename(chapter_file))[0]
            with open(chapter_file) as f:
                chapter_text = f.read()

            detect_file = os.path.join(work_dir, f'.detect-{ch_name}.txt')
            breaks = detect_explicit_breaks(chapter_text)

            if ch_name in detect_failed:
                log(f'\nProcessing chapter {chapter_num}: {ch_name}')
                log(f'  WARNING: scene detection failed ({detect_failed[ch_name]}); '
                    f'the chapter is not split')
                continue

            boundaries = []
            if os.path.isfile(detect_file):
                with open(detect_file) as f:
                    boundaries = parse_scene_boundaries(f.read())
                os.remove(detect_file)

            if breaks:
                log(f'\nProcessing chapter {chapter_num}: {ch_name}')
                log('  Found explicit scene break markers')
                splits = build_splits_from_markers(chapter_text, breaks)
                # Markers fix the boundaries; Claude's response names them
                named = {b['line_number']: b['title'] for b in boundaries}
                for split in splits:
                    split['slug'] = named.get(split['line'], '')
                if boundaries and len(named) != len(splits):
                    log(f'  WARNING: scene names returned for {len(named)} of '
                        f'{len(splits)} marked scenes')
            elif boundaries:
                log(f'\nProcessing chapter {chapter_num}: {ch_name}')
                splits = [
                    {'line': b['line_number'], 'slug': b['title'], 'title': '',
                     'reason': b['description'] or 'Claude detection'}
                    for b in boundaries
                ]
            elif args.dry_run:
                log(f'\nProcessing chapter {chapter_num}: {ch_name}')
                tw = count_words(chapter_text)
                log(f'  [DRY RUN] Would invoke Claude for scene detection ({tw} words)')
                continue
            else:
                log(f'\nProcessing chapter {chapter_num}: {ch_name}')
                log('  WARNING: No scene boundaries detected. Treating as single scene.')
                splits = [{'line': 1, 'slug': '', 'title': '', 'reason': 'Single scene'}]

            # Confirm and write
            if splits:
                if not confirm_splits(f'Chapter {chapter_num}: "{ch_name}"', chapter_text, splits):
                    log(f'  Skipped chapter {chapter_num}')
                    continue
                written = write_scene_files(chapter_text, chapter_num, part_num, seq_start, splits)
                total_new_scenes += len(written)

        log(f'\nSplit complete: {total_new_scenes} new scenes created from {len(chapter_files)} chapters')
        return total_new_scenes, len(chapter_files)

    # ==================================================================
    # Mode 3: Split manuscript into scenes
    # ==================================================================

    def do_split_manuscript():
        log('============================================')
        log('Mode: Split manuscript file into scenes')
        log('============================================')

        # Determine source file
        src_file = args.source
        if src_file:
            if not os.path.isabs(src_file):
                src_file = os.path.join(project_dir, src_file)
        else:
            for candidate in ['manuscript.md', 'manuscript/manuscript.md', 'manuscript.txt']:
                path = os.path.join(project_dir, candidate)
                if os.path.isfile(path):
                    src_file = path
                    break

        if not src_file or not os.path.isfile(src_file):
            log('ERROR: Manuscript file not found. Use --source to specify.')
            sys.exit(1)

        log(f'Source file: {src_file}')

        with open(src_file) as f:
            manuscript_text = f.read()
        total_words = count_words(manuscript_text)
        ms_lines = manuscript_text.splitlines()
        total_lines = len(ms_lines)
        log(f'Manuscript: {total_words} words, {total_lines} lines')

        # Step 1: Detect part and chapter boundaries
        chapter_starts = []
        chapter_names = []
        part_starts = []

        for line_num, line in enumerate(ms_lines, 1):
            stripped = line.strip()

            # Part headings divide chapters into parts; they are not chapters.
            # A heading stands on its own line between blank lines.
            if _is_part_heading(stripped):
                before = line_num == 1 or not ms_lines[line_num - 2].strip()
                after = line_num == total_lines or not ms_lines[line_num].strip()
                if before and after:
                    part_starts.append((line_num, stripped))
                    continue

            # Markdown chapter headings
            if re.match(r'^#{1,2}\s+Chapter', stripped, re.IGNORECASE):
                chapter_starts.append(line_num)
                chapter_names.append(re.sub(r'^#+\s*', '', stripped))
                continue

            # ALL CAPS chapter headings
            if re.match(r'^CHAPTER\s', stripped):
                chapter_starts.append(line_num)
                chapter_names.append(stripped)
                continue

            # "Chapter N" or "Chapter WORD"
            if re.match(r'^Chapter\s+[0-9IVXivx]+', stripped, re.IGNORECASE):
                chapter_starts.append(line_num)
                chapter_names.append(stripped)
                continue

            # Standalone number (chapter number)
            if re.match(r'^[0-9]+$', stripped) and len(stripped) <= 3:
                if line_num > 1:
                    prev = ms_lines[line_num - 2].strip()
                    if not prev:
                        chapter_starts.append(line_num)
                        chapter_names.append(f'Chapter {stripped}')

        # No chapter headings: fall back to any standalone markdown heading,
        # so books divided into staves, books or letters keep their divisions.
        # A heading with no prose before the next one (a title) is skipped and
        # left as front matter.
        if not chapter_starts:
            part_lines = {n for n, _ in part_starts}
            headings = [
                n for n, line in enumerate(ms_lines, 1)
                if n not in part_lines
                and re.match(r'^#{1,2}\s+\S', line.strip())
                and (n == 1 or not ms_lines[n - 2].strip())
                and (n == total_lines or not ms_lines[n].strip())
            ]
            bounds = sorted(headings + list(part_lines)) + [total_lines + 1]
            for n in headings:
                end = next(b for b in bounds if b > n)
                if any(l.strip() for l in ms_lines[n:end - 1]):
                    chapter_starts.append(n)
                    chapter_names.append(re.sub(r'^#+\s*', '', ms_lines[n - 1].strip()))

        if chapter_starts:
            log(f'Found {len(chapter_starts)} chapter boundaries')
        else:
            log('No chapter headings found.')
        if part_starts:
            log(f'Found {len(part_starts)} part headings')

        # Step 2: Build chapters. A part heading only marks where a part
        # begins; it never ends a chapter's text. Text between a part
        # heading and the next chapter opens that chapter; a part with no
        # chapter heading after it becomes a chapter of its own.
        def has_text(lines):
            return any(l.strip() for l in lines)

        units = sorted([(n, 'chapter', name) for n, name in zip(chapter_starts, chapter_names)]
                       + [(n, 'part', text) for n, text in part_starts])
        chapters = []   # (name, lines, part number or '')
        dropped_words = 0
        leading = ms_lines[:units[0][0] - 1] if units else ms_lines
        if has_text(leading):
            if chapter_starts:
                # As before: text ahead of the first chapter heading (title
                # page, epigraph) is front matter, not a scene. Say so.
                dropped_words = count_words('\n'.join(leading))
                log(f'  NOTE: {dropped_words} words before the first chapter heading '
                    f'are treated as front matter and not split into scenes')
            else:
                chapters.append(('Opening' if units else 'Manuscript', leading, ''))
        preamble, parts_seen = [], 0
        for i, (line_num, kind, name) in enumerate(units):
            next_line = units[i + 1][0] if i + 1 < len(units) else total_lines + 1
            if kind == 'chapter':
                chapters.append((name, preamble + ms_lines[line_num - 1:next_line - 1],
                                 parts_seen or ''))
                preamble = []
                continue
            parts_seen += 1
            body = ms_lines[line_num:next_line - 1]
            if has_text(body):
                if i + 1 < len(units) and units[i + 1][1] == 'chapter':
                    preamble = body
                else:
                    chapters.append((name, body, parts_seen))

        heading_words = sum(count_words(text) for _, text in part_starts)
        split_words = sum(count_words('\n'.join(lines)) for _, lines, _ in chapters)
        if split_words != total_words - heading_words - dropped_words:
            log(f'  WARNING: chapters hold {split_words} words but the manuscript has '
                f'{total_words - heading_words - dropped_words} outside headings and '
                f'front matter; check the split before relying on it')

        tmp_chapters_dir = os.path.join(work_dir, 'chapters')
        os.makedirs(tmp_chapters_dir, exist_ok=True)

        for c, (ch_name, lines, part_num) in enumerate(chapters):
            ch_slug = generate_slug(ch_name) or f'chapter-{c + 1}'
            # Prefix with the manuscript position: split-chapters orders
            # files by name, and slugs like chapter-ix / chapter-v do not
            # sort into reading order.
            ch_file = os.path.join(tmp_chapters_dir, f'{c + 1:04d}-{ch_slug}.md')
            chapter_parts[os.path.basename(ch_file)] = part_num
            ch_text = '\n'.join(lines)
            with open(ch_file, 'w') as f:
                f.write(ch_text + '\n')
            log(f'  Chapter {c + 1}: "{ch_name}" ({count_words(ch_text)} words)')

        # Step 3: Override source and use split-chapters logic
        # Temporarily set args.source to the temp directory
        original_source = args.source
        args.source = tmp_chapters_dir
        result = do_split_chapters()

        # Cleanup temp files
        import shutil
        shutil.rmtree(tmp_chapters_dir, ignore_errors=True)

        args.source = original_source
        return result

    # ==================================================================
    # Main execution
    # ==================================================================

    if args.rename:
        if not args.dry_run:
            create_branch('scenes-setup', project_dir)
            commit_and_push(project_dir, 'Scenes setup: pre-rename state')
            ensure_branch_pushed(project_dir)

        rename_count = do_rename()

        if not args.dry_run:
            commit_and_push(project_dir,
                            f'Scenes setup: rename {rename_count} scene files to slugs',
                            ['scenes/', 'reference/scenes.csv', 'reference/scene-intent.csv',
                             'reference/chapter-map.csv'])

            pr_body = f"""## Scene File Rename

**Project:** {title}
**Renamed:** {rename_count} files

### Tasks
- [x] Generate slugs from titles
- [x] Rename files with git mv
- [x] Update metadata.csv and intent.csv
- [x] Update chapter-map.csv"""

            create_draft_pr(f'Scenes setup: rename {rename_count} scene files',
                            pr_body, project_dir, 'drafting')
            log('Committed and pushed rename results')

    elif args.split_chapters:
        if not args.dry_run:
            create_branch('scenes-setup', project_dir)
            commit_and_push(project_dir, 'Scenes setup: pre-split state')
            ensure_branch_pushed(project_dir)

            # Cost forecast
            src_dir_est = args.source
            if src_dir_est:
                if not os.path.isabs(src_dir_est):
                    src_dir_est = os.path.join(project_dir, src_dir_est)
            else:
                for candidate in ['chapters', 'manuscript']:
                    d = os.path.join(project_dir, candidate)
                    if os.path.isdir(d):
                        src_dir_est = d
                        break

            if src_dir_est and os.path.isdir(src_dir_est):
                ch_count = 0
                total_w = 0
                for f in os.listdir(src_dir_est):
                    if f.endswith('.md') or f.endswith('.txt'):
                        fp = os.path.join(src_dir_est, f)
                        if os.path.isfile(fp):
                            ch_count += 1
                            with open(fp) as fh:
                                total_w += count_words(fh.read())
                if ch_count > 0:
                    avg_w = total_w // ch_count
                    split_cost = estimate_cost('evaluate', ch_count, avg_w, model)
                    log(f'Cost forecast (max): ~${split_cost:.6f} ({ch_count} chapters, avg {avg_w} words)')
                    if not check_threshold(split_cost):
                        log('Cost threshold check declined. Aborting.')
                        sys.exit(1)

        total_new_scenes, num_chapters = do_split_chapters()

        if not args.dry_run:
            commit_and_push(project_dir,
                            f'Scenes setup: split chapters into {total_new_scenes} scenes',
                            ['scenes/', 'reference/scenes.csv', 'reference/scene-intent.csv',
                             'working/'])

            pr_body = f"""## Chapter Split into Scenes

**Project:** {title}
**Chapters processed:** {num_chapters}
**Scenes created:** {total_new_scenes}

### Tasks
- [x] Detect scene break markers
- [x] Claude scene boundary detection (where needed)
- [x] Write scene files
- [x] Update metadata.csv and intent.csv"""

            create_draft_pr('Scenes setup: split chapters into scenes',
                            pr_body, project_dir, 'drafting')
            print_summary(project_dir, 'scene-detect', session_start=session_start)
            log('Committed and pushed split results')
        report_failed_detection()

    elif args.split_manuscript:
        if not args.dry_run:
            create_branch('scenes-setup', project_dir)
            commit_and_push(project_dir, 'Scenes setup: pre-split state')
            ensure_branch_pushed(project_dir)

        result = do_split_manuscript()
        total_new_scenes = result[0] if result else 0

        if not args.dry_run:
            commit_and_push(project_dir,
                            'Scenes setup: split manuscript into scenes',
                            ['scenes/', 'reference/scenes.csv', 'reference/scene-intent.csv',
                             'working/'])

            pr_body = f"""## Manuscript Split into Scenes

**Project:** {title}
**Scenes created:** {total_new_scenes}

### Tasks
- [x] Detect chapter boundaries
- [x] Split chapters into scenes
- [x] Write scene files
- [x] Update metadata.csv and intent.csv"""

            create_draft_pr('Scenes setup: split manuscript into scenes',
                            pr_body, project_dir, 'drafting')
            print_summary(project_dir, 'scene-detect', session_start=session_start)
            log('Committed and pushed split results')
        report_failed_detection()

    log('============================================')
    mode_name = 'rename' if args.rename else ('split-chapters' if args.split_chapters else 'split-manuscript')
    log(f'Scenes setup complete (mode: {mode_name})')
    log('============================================')
