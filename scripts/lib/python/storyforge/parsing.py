"""Scene extraction from Claude API responses.

Parses === SCENE: id === / === END SCENE: id === markers from Claude's
text output and writes each scene to its file. Replaces the bash regex
parsing that broke on macOS bash 3.x.
"""

import re
import os
import sys
import json


def extract_scenes_from_response(response: str, scene_dir: str) -> list[str]:
    """Extract scene blocks from a Claude response and write them to files.

    Args:
        response: The text content from Claude's API response.
        scene_dir: Path to the scenes/ directory where files are written.

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


def _write_scene(scene_id: str, lines: list[str], scene_dir: str, written: list[str]):
    """Write a scene's content to its file."""
    content = _trim_blank_lines('\n'.join(lines))
    if not content:
        return

    path = os.path.join(scene_dir, f'{scene_id}.md')
    with open(path, 'w') as f:
        f.write(content)
        f.write('\n')

    written.append(scene_id)


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

        response = extract_api_response(log_file)
        if not response:
            print('No response content found', file=sys.stderr)
            sys.exit(1)

        written = extract_scenes_from_response(response, scene_dir)
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
