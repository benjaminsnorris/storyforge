"""Scene extraction from Claude API responses.

Parses === SCENE: id === / === END SCENE: id === markers from Claude's
text output and writes each scene to its file. Replaces the bash regex
parsing that broke on macOS bash 3.x.
"""

import re
import os
import sys
import json


def _log(msg: str) -> None:
    """Log to stderr (avoids mixing with stdout scene-ID output)."""
    print(msg, file=sys.stderr)


def extract_scenes_from_response(response: str, scene_dir: str,
                                  stop_reason: str = 'end_turn') -> list[str]:
    """Extract scene blocks from a Claude response and write them to files.

    Args:
        response: The text content from Claude's API response.
        scene_dir: Path to the scenes/ directory where files are written.
        stop_reason: The API stop_reason. When 'max_tokens', the last scene
            without an end marker is discarded as likely truncated.

    Returns:
        List of scene IDs that were written.
    """
    start_pattern = re.compile(r'^=== SCENE:\s*(.+?)\s*===$', re.MULTILINE)
    end_pattern = re.compile(r'^=== END SCENE:', re.MULTILINE)

    scenes_written = []
    current_id = None
    current_lines = []

    for line in response.splitlines():
        start_match = start_pattern.match(line)
        end_match = end_pattern.match(line)

        if start_match and not line.startswith('=== END SCENE:'):
            # Write previous scene if any
            if current_id and current_lines:
                _write_scene(current_id, current_lines, scene_dir, scenes_written)

            new_id = start_match.group(1).strip()

            # Skip entries with parenthetical suffixes like "(revised note)"
            if '(' in new_id:
                current_id = None
                current_lines = []
                continue

            current_id = new_id
            current_lines = []

        elif end_match:
            if current_id and current_lines:
                _write_scene(current_id, current_lines, scene_dir, scenes_written)
            current_id = None
            current_lines = []

        elif current_id is not None:
            current_lines.append(line)

    # Write last scene if no end marker
    if current_id and current_lines:
        if stop_reason == 'max_tokens':
            _log(f'WARNING: Discarding truncated scene "{current_id}" '
                 f'(API response hit max_tokens limit)')
        else:
            _write_scene(current_id, current_lines, scene_dir, scenes_written)

    return scenes_written


def extract_single_scene(response: str) -> str | None:
    """Extract scene content from a single-scene response.

    If the response contains === SCENE: id === markers, extract the content
    between them. Otherwise return None (caller should use the full response).

    Args:
        response: The text content from Claude's API response.

    Returns:
        Extracted scene prose, or None if no markers found.
    """
    start_pattern = re.compile(r'^=== SCENE:\s*(.+?)\s*===$', re.MULTILINE)
    end_pattern = re.compile(r'^=== END SCENE:', re.MULTILINE)

    lines = response.splitlines()
    in_scene = False
    content_lines = []

    for line in lines:
        if start_pattern.match(line) and not line.startswith('=== END SCENE:'):
            in_scene = True
            content_lines = []
            continue
        elif end_pattern.match(line):
            if content_lines:
                return _trim_blank_lines('\n'.join(content_lines))
            in_scene = False
            continue
        elif in_scene:
            content_lines.append(line)

    if content_lines:
        return _trim_blank_lines('\n'.join(content_lines))

    return None


def extract_api_response(log_file: str) -> str:
    """Extract text content from an Anthropic Messages API JSON response.

    Args:
        log_file: Path to the JSON response file.

    Returns:
        The text content, or empty string on failure.
    """
    try:
        with open(log_file) as f:
            data = json.load(f)
        texts = []
        for block in data.get('content', []):
            if block.get('type') == 'text':
                texts.append(block.get('text', ''))
        return '\n'.join(texts)
    except (json.JSONDecodeError, FileNotFoundError, KeyError):
        return ''


_SENTENCE_ENDINGS = frozenset('.!?\u2019\u201d\u2014)\'"')
_WORD_COUNT_COLLAPSE_THRESHOLD = 0.6  # reject if new < 60% of original


def _write_scene(scene_id: str, lines: list[str], scene_dir: str, written: list[str]):
    """Write a scene's content to its file, with pre-write safety checks."""
    content = _trim_blank_lines('\n'.join(lines))
    if not content:
        return

    path = os.path.join(scene_dir, f'{scene_id}.md')

    # Safety: reject if content appears to end mid-sentence
    last_char = content.rstrip()[-1] if content.rstrip() else ''
    if last_char and last_char not in _SENTENCE_ENDINGS:
        _log(f'WARNING: Skipping "{scene_id}" -- appears to end mid-sentence '
             f'(last char: {last_char!r})')
        return

    # Safety: reject if word count collapsed >40% vs existing file
    if os.path.isfile(path):
        with open(path) as f:
            old_wc = len(f.read().split())
        new_wc = len(content.split())
        if old_wc > 100 and new_wc < old_wc * _WORD_COUNT_COLLAPSE_THRESHOLD:
            _log(f'WARNING: Skipping "{scene_id}" -- word count collapsed '
                 f'{old_wc} -> {new_wc} ({new_wc / old_wc:.0%}). '
                 f'Threshold is {_WORD_COUNT_COLLAPSE_THRESHOLD:.0%}.')
            return

    with open(path, 'w') as f:
        f.write(content)
        f.write('\n')

    written.append(scene_id)


def clean_scene_content(text: str) -> str:
    """Strip writing-agent artifacts from scene content.

    Removes two common artifacts that the writing agent sometimes produces:
    1. Leading H1/H2 scene title headers (and any blank lines after them)
    2. Trailing ``---`` separator followed by a Continuity Tracker Update block

    The result is trimmed of leading/trailing whitespace and given a single
    trailing newline.

    Args:
        text: Raw scene content (prose with possible artifacts).

    Returns:
        Cleaned scene content.
    """
    if not text or not text.strip():
        return text

    lines = text.splitlines()

    # --- Strip leading H1/H2 title headers ---
    # Skip any leading blank lines first, then check for a header.
    while lines and not lines[0].strip():
        lines.pop(0)
    if lines and re.match(r'^#{1,2}\s+\S', lines[0]):
        lines.pop(0)
        # Strip blank lines immediately after the removed header
        while lines and not lines[0].strip():
            lines.pop(0)

    # --- Strip trailing Continuity Tracker Update block ---
    # Look for a ``---`` separator followed by a ``# Continuity Tracker``
    # header (any heading level). Everything from the separator onward is
    # removed.
    separator_idx = None
    for i in range(len(lines) - 1, -1, -1):
        stripped = lines[i].strip()
        if re.match(r'^#{1,3}\s+[Cc]ontinuity\s+[Tt]racker', stripped):
            # Walk backwards to find the preceding ``---`` separator
            j = i - 1
            while j >= 0 and not lines[j].strip():
                j -= 1
            if j >= 0 and lines[j].strip() == '---':
                separator_idx = j
            else:
                # No separator — still strip from the header onward
                separator_idx = i
            break

    if separator_idx is not None:
        lines = lines[:separator_idx]

    # Final trim
    content = '\n'.join(lines).strip()
    return content + '\n' if content else ''


def _trim_blank_lines(text: str) -> str:
    """Remove leading and trailing blank lines."""
    lines = text.splitlines()
    # Strip leading blank lines
    while lines and not lines[0].strip():
        lines.pop(0)
    # Strip trailing blank lines
    while lines and not lines[-1].strip():
        lines.pop()
    return '\n'.join(lines)


# --- CLI interface for calling from bash ---

def main():
    """CLI entry point. Usage:

    python3 -m storyforge.parsing extract-scenes <log_file> <scene_dir>
    python3 -m storyforge.parsing extract-single <log_file> <scene_file>
    """
    if len(sys.argv) < 2:
        print('Usage: python3 -m storyforge.parsing <command> [args]', file=sys.stderr)
        sys.exit(1)

    command = sys.argv[1]

    if command == 'extract-scenes':
        if len(sys.argv) < 4:
            print('Usage: extract-scenes <log_file> <scene_dir>', file=sys.stderr)
            sys.exit(1)
        log_file = sys.argv[2]
        scene_dir = sys.argv[3]

        # Read stop_reason from the JSON response
        stop_reason = 'end_turn'
        try:
            with open(log_file) as f:
                data = json.load(f)
            stop_reason = data.get('stop_reason', 'end_turn')
        except (json.JSONDecodeError, FileNotFoundError):
            pass

        response = extract_api_response(log_file)
        if not response:
            print('No response content found', file=sys.stderr)
            sys.exit(1)

        written = extract_scenes_from_response(response, scene_dir,
                                                stop_reason=stop_reason)
        for sid in written:
            print(f'Wrote: {sid}')
        print(f'Total: {len(written)} scene(s)')

    elif command == 'extract-single':
        if len(sys.argv) < 4:
            print('Usage: extract-single <log_file> <scene_file>', file=sys.stderr)
            sys.exit(1)
        log_file = sys.argv[2]
        scene_file = sys.argv[3]

        response = extract_api_response(log_file)
        if not response:
            print('No response content found', file=sys.stderr)
            sys.exit(1)

        content = extract_single_scene(response)
        if content is not None:
            with open(scene_file, 'w') as f:
                f.write(content)
                f.write('\n')
        else:
            # No markers — write full response
            with open(scene_file, 'w') as f:
                f.write(response)
                f.write('\n')
        print(f'Wrote: {scene_file}')

    else:
        print(f'Unknown command: {command}', file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
