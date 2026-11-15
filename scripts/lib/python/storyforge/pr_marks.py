"""The author's marks on a pull request: line comments, suggestions, review
bodies and conversation comments (#654).

The voice rounds were marked in GitHub: each sample sentence on its own
line, a comment on the line ("keep", "cut", "more like this", or a reason),
`suggestion` blocks with the author's own wording, and general reactions in
reviews and the conversation. The rounds' lesson: read every page of
comments (`gh api --paginate`); round 1 had 66 line comments.

`fetch(pr, repo_dir)` returns them as `PrMarks`: `lines` (path, line, the
line's text when the file is given, the comment, a suggestion's text) and
`general` (review bodies and conversation comments, in order). A comment on
a line that later changed has no `line`; its `original_line` is used, and
said (`Comment.outdated`).
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field


class PrMarksError(RuntimeError):
    """The comments can't be read (no `gh`, no such PR, an API error)."""


@dataclass(frozen=True)
class Comment:
    """A comment on one line of a file in the PR."""
    path: str
    line: int
    body: str
    suggestion: str = ''
    outdated: bool = False


@dataclass
class PrMarks:
    lines: list[Comment] = field(default_factory=list)
    general: list[str] = field(default_factory=list)


_SUGGESTION = re.compile(r'```suggestion[^\n]*\n(.*?)```', re.S)


def _gh(repo_dir: str, path: str) -> list:
    """Every item of a paginated list endpoint, one JSON object per line
    (`--jq '.[] | @json'`), so pages join cleanly."""
    try:
        r = subprocess.run(['gh', 'api', '--paginate', path, '--jq', '.[] | @json'],
                           cwd=repo_dir, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise PrMarksError(f'gh could not be run ({e})') from e
    if r.returncode != 0:
        raise PrMarksError(f'gh api {path} failed: {r.stderr.strip()[:300]}')
    try:
        return [json.loads(line) for line in r.stdout.splitlines() if line.strip()]
    except json.JSONDecodeError as e:
        raise PrMarksError(f'gh api {path} returned what isn\'t JSON ({e})') from e


def parse_comment(item: dict) -> Comment | None:
    """A line comment from the API's shape (None for one on no line)."""
    line = item.get('line')
    outdated = line is None
    line = line if line is not None else item.get('original_line')
    if line is None:
        return None
    body = item.get('body') or ''
    m = _SUGGESTION.search(body)
    suggestion = m.group(1).rstrip('\n') if m else ''
    note = _SUGGESTION.sub('', body).strip()
    return Comment(item.get('path') or '', int(line), note, suggestion, outdated)


def files(pr: int, repo_dir: str) -> list[str]:
    """The paths PR `pr` changes.

    Raises:
        PrMarksError: as `_gh`.
    """
    return [f.get('filename', '') for f in _gh(repo_dir, f'repos/{{owner}}/{{repo}}/pulls/{pr}/files')]


def fetch(pr: int, repo_dir: str) -> PrMarks:
    """Every comment on PR `pr` of the repo at `repo_dir`, every page.

    Raises:
        PrMarksError: as `_gh`.
    """
    out = PrMarks()
    for item in _gh(repo_dir, f'repos/{{owner}}/{{repo}}/pulls/{pr}/comments'):
        c = parse_comment(item)
        if c is not None and (c.body or c.suggestion):
            out.lines.append(c)
    for item in _gh(repo_dir, f'repos/{{owner}}/{{repo}}/pulls/{pr}/reviews'):
        if (item.get('body') or '').strip():
            out.general.append(item['body'].strip())
    for item in _gh(repo_dir, f'repos/{{owner}}/{{repo}}/issues/{pr}/comments'):
        if (item.get('body') or '').strip():
            out.general.append(item['body'].strip())
    return out
