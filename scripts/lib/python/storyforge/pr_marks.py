"""The author's marks on a pull request: line comments, suggestions, review
bodies and conversation comments (#654).

The voice rounds were marked in GitHub: each sample sentence on its own
line, a comment on the line ("keep", "cut", "more like this", or a reason),
`suggestion` blocks with the author's own wording (an empty one: cut the
line), and general reactions in reviews and the conversation. The rounds'
lesson: read every page of comments (`gh api --paginate`); round 1 had 66
line comments.

`fetch(pr, repo_dir, since=)` returns them as `PrMarks`:

- `lines`: `Comment(path, line, body, suggestions, line_text, ...)`, paths
  relative to the repo's root. `line_text` is the commented line's text as
  GitHub showed it (the end of the comment's `diff_hunk`), so a caller can
  check that the line still says that. A comment on a line since changed
  keeps its `original_line` (`outdated`); one on several lines keeps its
  `start_line`. Each keeps GitHub's `id` and `created_at`, so a later run
  can leave out the comments an earlier one acted on (`revise
  --marks-from-pr`, #691).
- `general`: comments on a whole file, then review bodies and conversation
  comments, sorted by when they were made.
- `notes`: what was left out and why.

Only the PR author's comments count, never a bot's or anyone else's (the
review agents post on PRs too). Only a thread's first comment is a mark:
a reply ("Applied in <commit>", often posted with the author's own login)
is left out and named in `notes`, unless it holds a suggestion (#691). `since` (an ISO time: the round's commit)
leaves out general comments made before it, so an earlier round's
reactions aren't read again. Comments in a review not yet submitted can't
be read: GitHub doesn't show them.
"""

from __future__ import annotations

import base64
import json
import re
import subprocess
from dataclasses import dataclass, field


class PrMarksError(RuntimeError):
    """The comments can't be read (no `gh`, no such PR, an API error)."""


@dataclass(frozen=True)
class Comment:
    """A comment on a line (or lines) of a file in the PR."""
    path: str
    line: int
    body: str
    #: each suggestion block's text, in order; '' is one that cuts the line
    suggestions: tuple[str, ...] = ()
    outdated: bool = False
    #: the commented line's text as GitHub showed it ('' when unknown)
    line_text: str = ''
    start_line: int | None = None
    #: GitHub's id for the comment (0 when unknown), and when it was made
    id: int = 0
    created_at: str = ''

    @property
    def suggestion(self) -> str:
        """The first suggestion's text ('' with none)."""
        return self.suggestions[0] if self.suggestions else ''


@dataclass
class PrMarks:
    lines: list[Comment] = field(default_factory=list)
    general: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


_SUGGESTION = re.compile(r'```suggestion[^\n]*\n(.*?)```', re.S)


def _gh_api(repo_dir: str, path: str, paginate: bool = True) -> list:
    """Every item of a list endpoint (or the one object of another), one
    JSON value per line (`--jq`), so pages join cleanly.

    Raises:
        PrMarksError: gh can't run, fails, or answers what isn't JSON.
    """
    args = ['gh', 'api'] + (['--paginate'] if paginate else []) + [
        path, '--jq', '.[] | @json' if paginate else '@json']
    try:
        r = subprocess.run(args, cwd=repo_dir, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise PrMarksError(f'gh could not be run ({e})') from e
    if r.returncode != 0:
        raise PrMarksError(f'gh api {path} failed: {r.stderr.strip()[:300]}')
    try:
        return [json.loads(line) for line in r.stdout.splitlines() if line.strip()]
    except json.JSONDecodeError as e:
        raise PrMarksError(f'gh api {path} returned what isn\'t JSON ({e})') from e


def _line_text(hunk: str) -> str:
    """The last line of a diff hunk (the commented one), without its sign."""
    lines = [ln for ln in (hunk or '').replace('\r\n', '\n').split('\n') if ln]
    if not lines:
        return ''
    last = lines[-1]
    return (last[1:] if last[:1] in '+- ' else last).strip()


def parse_comment(item: dict) -> Comment | None:
    """A line comment from the API's shape; None for one on a whole file
    or on the old side of the diff (a deleted line). A thread's replies are
    the caller's to drop (`fetch` does)."""
    if item.get('subject_type') == 'file' or item.get('side') == 'LEFT':
        return None
    line = item.get('line')
    outdated = line is None
    line = line if line is not None else item.get('original_line')
    if line is None:
        return None
    body = (item.get('body') or '').replace('\r\n', '\n')
    suggestions = tuple(s.rstrip('\n') for s in _SUGGESTION.findall(body))
    note = _SUGGESTION.sub('', body).strip()
    start = item.get('original_start_line') if outdated else item.get('start_line')
    return Comment(item.get('path') or '', int(line), note, suggestions, outdated,
                   _line_text(item.get('diff_hunk') or ''), start,
                   int(item.get('id') or 0), item.get('created_at') or '')


def _is_bot(user: dict | None) -> bool:
    user = user or {}
    return user.get('type') == 'Bot' or (user.get('login') or '').endswith('[bot]')


def pr_info(pr: int, repo_dir: str) -> dict:
    """The PR's author login, head commit, head branch and changed paths
    (from the repo's root).

    Raises:
        PrMarksError: as `_gh_api`, or no such PR.
    """
    obj = _gh_api(repo_dir, f'repos/{{owner}}/{{repo}}/pulls/{pr}', paginate=False)
    if not obj or not isinstance(obj[0], dict):
        raise PrMarksError(f'PR #{pr} was not found')
    head = obj[0]
    paths = [f.get('filename', '') for f in
             _gh_api(repo_dir, f'repos/{{owner}}/{{repo}}/pulls/{pr}/files')]
    return {'author': (head.get('user') or {}).get('login', ''),
            'head_sha': (head.get('head') or {}).get('sha', ''),
            'head_ref': (head.get('head') or {}).get('ref', ''), 'paths': paths}


def file_at(repo_dir: str, path: str, ref: str) -> str:
    """`path` (from the repo's root) as it is at commit `ref`, from GitHub.

    Raises:
        PrMarksError: as `_gh_api`, or the file isn't there.
    """
    obj = _gh_api(repo_dir, f'repos/{{owner}}/{{repo}}/contents/{path}?ref={ref}',
                  paginate=False)
    try:
        return base64.b64decode(obj[0]['content']).decode('utf-8')
    except (IndexError, KeyError, TypeError, ValueError) as e:
        raise PrMarksError(f'{path} at {ref[:10]} could not be read ({e})') from e


def fetch(pr: int, repo_dir: str, since: str = '', author: str = '') -> PrMarks:
    """The PR author's comments on PR `pr`, every page (`author` names
    another login whose comments count); general comments made before
    `since` (ISO 8601) left out. What's left out is counted in `notes`.

    Raises:
        PrMarksError: as `_gh_api`.
    """
    out = PrMarks()
    who = author or pr_info(pr, repo_dir)['author']
    others: dict[str, int] = {}
    earlier = left_side = 0
    replies: list[str] = []
    general: list[tuple[str, str]] = []

    def theirs(item) -> bool:
        user = item.get('user') or {}
        if _is_bot(user) or (who and user.get('login') != who):
            name = user.get('login') or '?'
            others[name] = others.get(name, 0) + 1
            return False
        return True

    for item in _gh_api(repo_dir, f'repos/{{owner}}/{{repo}}/pulls/{pr}/comments'):
        if not theirs(item):
            continue
        if item.get('in_reply_to_id') and not _SUGGESTION.search(item.get('body') or ''):
            # an answer in a thread ("Applied in ..."), not a mark
            replies.append(f'{item.get("path")}:{item.get("line") or item.get("original_line")}')
            continue
        c = parse_comment(item)
        if c is None:
            body = (item.get('body') or '').strip()
            if item.get('side') == 'LEFT':
                left_side += 1
            elif body:
                general.append((item.get('created_at') or '',
                                f'On {item.get("path")} as a whole: {body}'))
            continue
        if c.body or c.suggestions:
            out.lines.append(c)
    for kind in ('pulls', 'issues'):
        endpoint = 'reviews' if kind == 'pulls' else 'comments'
        for item in _gh_api(repo_dir, f'repos/{{owner}}/{{repo}}/{kind}/{pr}/{endpoint}'):
            body = (item.get('body') or '').strip()
            if not body or not theirs(item):
                continue
            when = item.get('submitted_at') or item.get('created_at') or ''
            if since and when and when < since:
                earlier += 1
                continue
            general.append((when, body))
    out.general = [b for _, b in sorted(general, key=lambda t: t[0])]
    if others:
        out.notes.append('comments not by the PR\'s author, left out: ' + ', '.join(
            f'{n} by {name}' for name, n in sorted(others.items())))
    if earlier:
        out.notes.append(f'{earlier} general comment(s) from before this round, left out')
    if left_side:
        out.notes.append(f'{left_side} comment(s) on deleted lines, left out')
    if replies:
        out.notes.append(f'{len(replies)} repl(ies) in comment threads, left out (only a '
                         f'thread\'s first comment, or a reply with a suggestion, is a mark; '
                         f'put a new note in its own comment): {", ".join(replies)}')
    return out
