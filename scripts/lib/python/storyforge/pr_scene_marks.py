"""The author's marks on drafted scenes, read from the scenes' pull request
(`storyforge revise --marks-from-pr N`, #691).

`write --session` drafts scenes onto a branch with a draft PR, and the
author marks them there, as they marked the voice rounds: line comments,
`suggestion` blocks, general reactions. `map_comments` turns the PR's
comments (`pr_marks.fetch`) into the same `marks.SceneMarks` a marks file
gives (`marks.parse_marks`), plus the suggestions to apply and what was
left out and why.

A scene file holds about a paragraph per line (the drafter writes
paragraphs; `parsing.clean_scene_content` doesn't reflow them), so a line
comment marks a paragraph:

- **The scene:** a comment on `scenes/<id>.md` belongs to scene `<id>`; a
  comment on any other file is left out and named.
- **The quote:** the words the comment quotes (`>` lines, or a "quoted"
  phrase at the start or end of the comment) when they're in the
  paragraph; otherwise the whole paragraph (and the note says what it
  quoted). A comment over several lines marks them all.
- **The note:** the comment without the quoted words. Empty, or one of
  `marks.KEEP_NOTES`: a keep.
- **A `suggestion` block** is the author's own wording, so nothing
  rewrites it: it's applied as written (`apply_suggestions`), before the
  reviser runs, in its own commit; an empty one cuts the lines. Its text
  is then a keep, so the reviser can't touch it. A comment with more than
  one suggestion, or one overlapping an earlier suggestion, is left out;
  other comments on a suggestion's lines are left out (the line is now
  the author's).
- **Left out, never guessed:** an outdated comment (its line changed
  since), one whose line no longer says what GitHub showed
  (`Comment.line_text`), one on a blank line or an illustration marker.
  General comments (review bodies, the conversation, comments on a whole
  file) are listed, never sent: they aren't tied to a line.

Each run's record (`voice_review.record`) names the comments it acted on
(`used_note`): its changes and its suggestions. A later run over the same
PR leaves those out (`used_comment_ids`). Keeps are never "acted on", so
they stay examples for later runs while their lines still match.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from storyforge.marks import Mark, SceneMarks, is_keep

_SCENE_PATH = re.compile(r'\Ascenes/([^/]+)\.md\Z')
_INLINE_QUOTE = re.compile(r'"([^"\n]+)"|“([^”\n]+)”')
_EDGE = ' \t\n:;,.-–—'
_USED = re.compile(r'^NOTE: Comments used from PR #(\d+): ([\d, ]+)\s*$', re.M)


@dataclass(frozen=True)
class Suggestion:
    """A suggestion block to apply as written: file lines `start`..`end`
    (1-based, inclusive) of `scenes/<scene_id>.md` become `text` ('' cuts
    them)."""
    scene_id: str
    start: int
    end: int
    text: str
    note: str = ''
    comment_id: int = 0


@dataclass
class Mapped:
    """What a PR's comments come to."""
    scenes: list[SceneMarks] = field(default_factory=list)
    suggestions: list[Suggestion] = field(default_factory=list)
    #: per scene, the ids of the comments asking for a change
    change_ids: dict[str, list[int]] = field(default_factory=dict)
    #: each comment left out, with why
    left_out: list[str] = field(default_factory=list)
    #: comments an earlier run acted on, or made before --since: counted
    already_used: int = 0
    before_since: int = 0
    general: list[str] = field(default_factory=list)

    def scene(self, sid: str) -> SceneMarks:
        for sm in self.scenes:
            if sm.scene_id == sid:
                return sm
        sm = SceneMarks(sid)
        self.scenes.append(sm)
        return sm

    @property
    def has_work(self) -> bool:
        """Whether anything is left to send: a suggestion or a change."""
        return bool(self.suggestions) or any(sm.changes for sm in self.scenes)


def _is_marker(line: str) -> bool:
    from storyforge.illustrations import MARKER_ANY_RE, MARKER_LINE_RE
    s = line.strip()
    return bool(MARKER_LINE_RE.fullmatch(s) or MARKER_ANY_RE.fullmatch(s)
                or (s.startswith('<!--') and s.endswith('-->')))


def _prose(lines: list[str]) -> str:
    """The commented lines' prose, as `read_scene_prose` gives it: marker
    lines and inline markers out, paragraphs kept apart."""
    from storyforge.illustrations import MARKER_ANY_RE
    text = '\n'.join(ln for ln in lines if not _is_marker(ln))
    return re.sub(r'\n{3,}', '\n\n', MARKER_ANY_RE.sub('', text)).strip()


def _found(quote: str, paragraph: str) -> bool:
    from storyforge.voice_review import flag_spans
    return bool(quote.strip()) and bool(flag_spans(paragraph, quote))


def split_body(body: str, paragraph: str) -> tuple[str, str]:
    """(the quote, the note) from a comment on `paragraph`: the words the
    comment quotes when they're in the paragraph, else the paragraph."""
    lines = body.replace('\r\n', '\n').split('\n')
    quoted = ' '.join(ln[1:].strip() for ln in lines if ln.startswith('>')).strip()
    rest = ' '.join(ln.strip() for ln in lines if not ln.startswith('>')).strip()
    if quoted:
        if _found(quoted, paragraph):
            return quoted, rest.strip(_EDGE)
        return paragraph, (f'{rest} ' if rest else '') + f'(the comment quoted "{quoted}")'
    text = body.strip()
    for m in _INLINE_QUOTE.finditer(text):
        words = m.group(1) or m.group(2)
        at_edge = not text[:m.start()].strip(_EDGE) or not text[m.end():].strip(_EDGE)
        if at_edge and _found(words, paragraph):
            return words, (text[:m.start()] + ' ' + text[m.end():]).strip(_EDGE)
    return paragraph, text


def _scene_id(path: str, prefix: str) -> str:
    """The scene a comment's path (from the repo's root) is on, or ''."""
    if prefix and not path.startswith(prefix):
        return ''
    m = _SCENE_PATH.match(path[len(prefix):])
    return m.group(1) if m else ''


def map_comments(prs, read_scene, prefix: str = '', skip_ids=frozenset(),
                 since: str = '') -> Mapped:
    """The PR's line comments (`prs`, a `pr_marks.PrMarks`) as each scene's
    marks and suggestions. `read_scene(sid)` gives `scenes/<sid>.md` as it
    is at the PR's head ('' when there's none); `prefix` is the project's
    folder in the repo ('' at its root, else ending in '/'). Comments whose
    id is in `skip_ids`, or made before `since` (ISO 8601), are counted
    and left out."""
    out = Mapped(general=list(prs.general))
    texts: dict[str, list[str]] = {}
    marks: list[tuple[str, int, int, Mark, int]] = []
    for c in prs.lines:
        where = f'{c.path}:{c.line}'
        sid = _scene_id(c.path, prefix)
        if not sid:
            out.left_out.append(f'{where}: not on a scene file')
            continue
        if c.id and c.id in skip_ids:
            out.already_used += 1
            continue
        if since and c.created_at and c.created_at < since:
            out.before_since += 1
            continue
        if c.outdated:
            out.left_out.append(f'{where}: outdated (its line has changed since the comment)')
            continue
        if sid not in texts:
            texts[sid] = (read_scene(sid) or '').replace('\r\n', '\n').split('\n')
        lines = texts[sid]
        start = c.start_line if c.start_line and c.start_line <= c.line else c.line
        if not lines or c.line > len(lines) or start < 1:
            out.left_out.append(f'{where}: the scene file has no line {c.line}')
            continue
        if not c.line_text:
            out.left_out.append(f'{where}: GitHub didn\'t show the line\'s text, so it can\'t '
                                f'be checked against the scene')
            continue
        if lines[c.line - 1].strip() != c.line_text:
            out.left_out.append(f'{where}: the line no longer says what it said when marked')
            continue
        if len(c.suggestions) > 1:
            out.left_out.append(f'{where}: {len(c.suggestions)} suggestions in one comment; '
                                f'give each its own comment')
            continue
        if c.suggestions:
            out.suggestions.append(Suggestion(sid, start, c.line, c.suggestions[0],
                                              c.body.strip(), c.id))
            continue
        paragraph = _prose(lines[start - 1:c.line])
        if not paragraph:
            out.left_out.append(f'{where}: on a blank line or an illustration marker')
            continue
        quote, note = split_body(c.body, paragraph)
        marks.append((sid, start, c.line, Mark(quote, note or 'keep'), c.id))
    # suggestions: the first on a line wins; the lines are then the author's
    taken: dict[str, list[tuple[int, int]]] = {}
    kept = []
    for s in out.suggestions:
        spans = taken.setdefault(s.scene_id, [])
        if any(s.start <= b and a <= s.end for a, b in spans):
            out.left_out.append(f'{prefix}scenes/{s.scene_id}.md:{s.end}: a suggestion '
                                f'overlapping an earlier one')
            continue
        spans.append((s.start, s.end))
        kept.append(s)
    out.suggestions = kept
    for sid, a, b, mark, cid in sorted(marks, key=lambda t: (t[0], t[1])):
        if any(a <= y and x <= b for x, y in taken.get(sid, [])):
            out.left_out.append(f'{prefix}scenes/{sid}.md:{b}: its line has the author\'s '
                                f'suggestion, applied as written')
            continue
        out.scene(sid).marks.append(mark)
        if not is_keep(mark) and cid:
            out.change_ids.setdefault(sid, []).append(cid)
    for s in out.suggestions:
        if s.text.strip():
            out.scene(s.scene_id).marks.append(Mark(s.text.strip(), 'keep'))
    return out


def apply_suggestions(text: str, suggestions: list[Suggestion]) -> str:
    """`text` (a scene file) with each suggestion's lines replaced by its
    wording, as written; an empty one cuts its lines (and the blank line
    left doubled). The suggestions mustn't overlap (`map_comments`)."""
    nl = '\r\n' if '\r\n' in text else '\n'
    lines = text.replace('\r\n', '\n').split('\n')
    for s in sorted(suggestions, key=lambda s: s.start, reverse=True):
        new = s.text.split('\n') if s.text else []
        lines[s.start - 1:s.end] = new
        i = s.start - 1
        if not new and 0 < i < len(lines) and not lines[i].strip() and not lines[i - 1].strip():
            del lines[i]
    return nl.join(lines)


def used_comment_ids(project_dir: str, pr: int) -> set[int]:
    """The ids of PR `pr`'s comments an earlier run acted on, from the
    records in working/voice-reviews/."""
    from storyforge.voice_review import REVIEWS_DIR
    folder = os.path.join(project_dir, REVIEWS_DIR)
    ids: set[int] = set()
    try:
        names = sorted(os.listdir(folder))
    except FileNotFoundError:
        return ids
    for name in names:
        if name.endswith('.md'):
            with open(os.path.join(folder, name), encoding='utf-8', errors='replace') as f:
                ids |= _ids_in(f.read()).get(pr, set())
    return ids


def _ids_in(text: str) -> dict[int, set[int]]:
    found: dict[int, set[int]] = {}
    for m in _USED.finditer(text):
        found.setdefault(int(m.group(1)), set()).update(
            int(x) for x in re.findall(r'\d+', m.group(2)))
    return found


def used_notes(project_dir: str, sid: str, pr: int = 0, new_ids=()) -> list[str]:
    """The record's notes naming the comments used, for scene `sid`: those
    its record already names (every PR's), with `new_ids` added under PR
    `pr`. A record rewritten keeps what the earlier one named."""
    from storyforge.voice_review import REVIEWS_DIR
    try:
        with open(os.path.join(project_dir, REVIEWS_DIR, f'{sid}.md'),
                  encoding='utf-8', errors='replace') as f:
            found = _ids_in(f.read())
    except FileNotFoundError:
        found = {}
    if pr and new_ids:
        found.setdefault(pr, set()).update(new_ids)
    return [f'Comments used from PR #{n}: {", ".join(str(i) for i in sorted(ids))}'
            for n, ids in sorted(found.items()) if ids]


def describe(mapped: Mapped, pr: int) -> list[str]:
    """What the run would send and what it left out, for the log."""
    out = []
    by_scene: dict[str, list[Suggestion]] = {}
    for s in mapped.suggestions:
        by_scene.setdefault(s.scene_id, []).append(s)
    sids = [sm.scene_id for sm in mapped.scenes]
    sids += [sid for sid in by_scene if sid not in sids]
    for sid in sids:
        out.append(f'{sid}:')
        for s in by_scene.get(sid, []):
            lines = f'line {s.end}' if s.start == s.end else f'lines {s.start}-{s.end}'
            what = f'"{s.text[:120]}"' if s.text else '(cut)'
            out.append(f'  suggestion on {lines}, applied as written: {what}'
                       + (f' (its note: {s.note[:120]})' if s.note else ''))
        sm = next((m for m in mapped.scenes if m.scene_id == sid), None)
        for m in (sm.changes if sm else []):
            out.append(f'  change: "{m.quote[:120]}" -- {m.note[:200]}')
        for m in (sm.keeps if sm else []):
            out.append(f'  keep: "{m.quote[:120]}"')
    if mapped.already_used:
        out.append(f'{mapped.already_used} comment(s) an earlier run on PR #{pr} acted on, '
                   f'left out')
    if mapped.before_since:
        out.append(f'{mapped.before_since} comment(s) made before --since, left out')
    for why in mapped.left_out:
        out.append(f'Left out: {why}')
    for g in mapped.general:
        out.append(f'General comment (not sent; it isn\'t tied to a line): {g[:300]}')
    return out
