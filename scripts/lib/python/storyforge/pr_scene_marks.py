"""The author's marks on drafted scenes, read from the scenes' pull request
(`storyforge revise --marks-from-pr N`, #691).

`write --session` drafts scenes onto a branch with a draft PR, and the
author marks them there, as they marked the voice rounds: line comments,
`suggestion` blocks, general reactions. `map_comments` turns the PR's
comments (`pr_marks.fetch`) into the same `marks.SceneMarks` a marks file
gives (`marks.parse_marks`), plus the suggestions to apply and what was
left out and why.

A scene file holds a sentence per line (`scene_layout`; a scene drafted
before that, a paragraph per line), so a line comment marks its line, a
sentence:

- **The scene:** a comment on `scenes/<id>.md` belongs to scene `<id>`; a
  comment on any other file is left out and named.
- **The quote:** the words the comment quotes (`>` lines, or a "quoted"
  phrase at the start or end of the comment) when they're in the
  commented lines; otherwise those lines (and the note says what it
  quoted). A comment over several lines marks them all. The reviser finds
  a quote by its first occurrence, so a quote must occur once in the
  scene, as the reviser's edit must: quoted words that occur more than
  once give way to the commented lines, and lines that occur more than once
  (a short sentence, `"No."`) take in the line before or after them in
  their paragraph until they're unique (`_widen`; a keep, never edited,
  needs only to be the first occurrence: `_placed`). The note says so,
  unless the mark is a keep. Lines that can't be placed are left out and
  named.
- **The note:** the comment without the quoted words. Empty, or one of
  `marks.KEEP_NOTES`: a keep.
- **A `suggestion` block** is the author's own wording, so nothing
  rewrites it: it's applied as written (`apply_suggestions`), before the
  reviser runs, in its own commit; an empty one cuts the lines. Its text
  is then a keep (`with_suggestion_keeps`), so the reviser can't touch it.
  A comment with more than one suggestion, one overlapping an earlier
  suggestion, or one that would remove an illustration marker is left
  out; other comments on a suggestion's lines are left out (the line is
  now the author's). A suggestion comment's other words are shown, not
  sent.
- **Left out, never guessed:** an outdated comment (its line changed
  since), one whose line no longer says what GitHub showed
  (`Comment.line_text`; only a range's last line can be checked), one on a
  blank line or an illustration marker, on a scene file that isn't here.
  General comments (review bodies, the conversation, comments on a whole
  file) are listed, never sent: they aren't tied to a line.

Each run's record (`voice_review.record`) names the comments it acted on
(`used_notes`): its suggestions, and the changes the reviser rewrote or
kept (saying why). A change it didn't answer, or whose edit was refused,
or a revision rolled back, isn't used up. A later run over the same PR
leaves the used ones out (`used_comment_ids`), naming each. Keeps are
never "acted on", so they stay examples for later runs while their lines
still match.
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
    them). `note`: the comment's other words, shown, not sent."""
    scene_id: str
    start: int
    end: int
    text: str
    note: str = ''
    comment_id: int = 0

    def __post_init__(self):
        if not 1 <= self.start <= self.end:
            raise ValueError(f'a suggestion on lines {self.start}-{self.end}')


@dataclass
class Mapped:
    """What a PR's comments come to. `scenes` hold the marks from comments
    (each `Mark.comment_id` set); the suggestions' wording becomes a keep
    only once they're applied (`with_suggestion_keeps`)."""
    scenes: list[SceneMarks] = field(default_factory=list)
    suggestions: list[Suggestion] = field(default_factory=list)
    #: each comment left out, with why
    left_out: list[str] = field(default_factory=list)
    #: comments an earlier run acted on, or made before --since (also named
    #: in `left_out`)
    already_used: int = 0
    before_since: int = 0
    general: list[str] = field(default_factory=list)

    @property
    def has_work(self) -> bool:
        """Whether anything is left to send: a suggestion or a change."""
        return bool(self.suggestions) or any(sm.changes for sm in self.scenes)


def _scene_for(scenes: list[SceneMarks], sid: str) -> SceneMarks:
    """`sid`'s entry in `scenes`, added when there's none."""
    for sm in scenes:
        if sm.scene_id == sid:
            return sm
    sm = SceneMarks(sid)
    scenes.append(sm)
    return sm


def with_suggestion_keeps(mapped: Mapped) -> list[SceneMarks]:
    """`mapped.scenes`, each applied suggestion's wording added as a keep
    (the reviser may not touch it). For after `apply_suggestions`."""
    scenes = [SceneMarks(sm.scene_id, list(sm.marks)) for sm in mapped.scenes]
    for s in mapped.suggestions:
        if s.text.strip():
            _scene_for(scenes, s.scene_id).marks.append(Mark(s.text.strip(), 'keep'))
    return scenes


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


def _found(quote: str, commented: str) -> bool:
    from storyforge.voice_review import flag_spans
    return bool(quote.strip()) and bool(flag_spans(commented, quote))


def split_body(body: str, commented: str) -> tuple[str, str]:
    """(the quote, the note) from a comment on the lines `commented`: the
    words the comment quotes when they're in those lines, else the lines."""
    lines = body.replace('\r\n', '\n').split('\n')
    quoted = ' '.join(ln[1:].strip() for ln in lines if ln.startswith('>')).strip()
    rest = ' '.join(ln.strip() for ln in lines if not ln.startswith('>')).strip()
    if quoted:
        if _found(quoted, commented):
            return quoted, rest.strip(_EDGE)
        return commented, (f'{rest} ' if rest else '') + f'(the comment quoted "{quoted}")'
    text = body.strip()
    for m in _INLINE_QUOTE.finditer(text):
        words = m.group(1) or m.group(2)
        at_edge = not text[:m.start()].strip(_EDGE) or not text[m.end():].strip(_EDGE)
        if at_edge and _found(words, commented):
            return words, (text[:m.start()] + ' ' + text[m.end():]).strip(_EDGE)
    return commented, text


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
    is at the PR's head (None when there's none); `prefix` is the project's
    folder in the repo ('' at its root, else ending in '/'). Comments whose
    id is in `skip_ids`, or made before `since` (UTC, `...Z`, as GitHub
    gives times), are left out. Every comment left out is named."""
    from storyforge.illustrations import MARKER_ANY_RE
    out = Mapped(general=list(prs.general))
    texts: dict[str, list[str] | None] = {}
    marks: list[tuple[str, int, int, Mark]] = []
    for c in prs.lines:
        where = f'{c.path}:{c.line}'
        sid = _scene_id(c.path, prefix)
        if not sid:
            out.left_out.append(f'{where}: not on a scene file')
            continue
        if c.id and c.id in skip_ids:
            out.already_used += 1
            out.left_out.append(f'{where}: an earlier run acted on it (comment {c.id})')
            continue
        if since and c.created_at and c.created_at < since:
            out.before_since += 1
            out.left_out.append(f'{where}: made before --since ({c.created_at})')
            continue
        if c.outdated:
            out.left_out.append(f'{where}: outdated (its line has changed since the comment)')
            continue
        if sid not in texts:
            raw = read_scene(sid)
            texts[sid] = None if raw is None else raw.replace('\r\n', '\n').split('\n')
        lines = texts[sid]
        if lines is None:
            out.left_out.append(f'{where}: there is no scene file {sid}.md here')
            continue
        if c.start_line and c.start_line > c.line:
            out.left_out.append(f'{where}: its lines run backwards (from {c.start_line})')
            continue
        start = c.start_line or c.line
        if c.line > len(lines) or start < 1:
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
            text = c.suggestions[0]
            span = '\n'.join(lines[start - 1:c.line])
            lost = [m for m in MARKER_ANY_RE.findall(span) if f'[[illus:{m}]]' not in text]
            if lost:
                out.left_out.append(f'{where}: the suggestion would remove illustration '
                                    f'marker(s) {", ".join(lost)}; keep them in it, or move '
                                    f'them with `storyforge illustrate` first')
                continue
            out.suggestions.append(Suggestion(sid, start, c.line, text, c.body.strip(), c.id))
            continue
        commented = _prose(lines[start - 1:c.line])
        if not commented:
            out.left_out.append(f'{where}: on a blank line or an illustration marker')
            continue
        quote, note = split_body(c.body, commented)
        keep = is_keep(Mark(quote, note or 'keep'))
        whole = _prose(lines)
        if quote != commented and not _unique(quote, whole):
            if not keep:   # a keep stays a keep: the reviser never edits it
                note = f'{note} (on "{quote}", which occurs more than once in the scene)'
            quote = commented
        if not _placed(quote, lines, start, whole, keep):
            wider = _widen(lines, start, c.line, whole, keep)
            if not wider:
                out.left_out.append(f'{where}: its line occurs more than once in the scene, '
                                    f'with the lines around it too; quote words that occur '
                                    f'once')
                continue
            if not keep:
                note = (f'{note} (its line occurs more than once in the scene, so the '
                        f'line next to it is in the quote)')
            quote = wider
        marks.append((sid, start, c.line, Mark(quote, note.strip() or 'keep', c.id)))
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
    for sid, a, b, mark in sorted(marks, key=lambda t: (t[0], t[1])):
        if any(a <= y and x <= b for x, y in taken.get(sid, [])):
            out.left_out.append(f'{prefix}scenes/{sid}.md:{b}: its line has the author\'s '
                                f'suggestion, applied as written')
            continue
        _scene_for(out.scenes, sid).marks.append(mark)
    return out


def _widen(lines: list[str], start: int, end: int, prose: str, keep: bool) -> str:
    """The commented lines `start`..`end` (1-based) with the line before or
    after them in their paragraph (or both), the first of those `_placed`
    in `prose`; '' when none is."""
    def usable(n: int) -> bool:
        return 1 <= n <= len(lines) and bool(lines[n - 1].strip()) and \
            not _is_marker(lines[n - 1])
    for lo, hi in ((start - 1, end), (start, end + 1), (start - 1, end + 1)):
        if (lo == start or usable(lo)) and (hi == end or usable(hi)):
            quote = _prose(lines[lo - 1:hi])
            if _placed(quote, lines, lo, prose, keep):
                return quote
    return ''


def _placed(quote: str, lines: list[str], start: int, prose: str, keep: bool) -> bool:
    """Whether a mark quoting `quote` (lines from `start`, 1-based) works:
    a change needs words that occur once, since the reviser's edit must
    (`scene_layout.find_span`); a keep, never edited, needs only that its
    first occurrence, which the reviser protects, is these lines."""
    if _unique(quote, prose):
        return True
    return keep and quote in prose and quote not in _prose(lines[:start - 1])


def _unique(quote: str, prose: str) -> bool:
    """Whether the reviser would find `quote` in one place only: an exact
    match occurring once (its first match is where it lands)."""
    n = prose.count(quote.strip())
    return n == 1 or (n == 0 and _found(quote, prose))


def apply_suggestions(text: str, suggestions: list[Suggestion]) -> str:
    """`text` (a scene file) with each suggestion's lines replaced by its
    wording, as written; an empty one cuts its lines (and the blank line
    left doubled, or leading).

    Raises:
        ValueError: suggestions that overlap, or a line past the file's end.
    """
    nl = '\r\n' if '\r\n' in text else '\n'
    lines = text.replace('\r\n', '\n').split('\n')
    after = len(lines) + 1
    for s in sorted(suggestions, key=lambda s: s.start, reverse=True):
        if s.end >= after or s.end > len(lines):
            raise ValueError(f'a suggestion on lines {s.start}-{s.end} overlaps another or '
                             f'runs past the file')
        after = s.start
        new = s.text.split('\n') if s.text else []
        lines[s.start - 1:s.end] = new
        i = s.start - 1
        if not new and i < len(lines) and not lines[i].strip() and (
                i == 0 or not lines[i - 1].strip()):
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
                       + (f' (its note, not sent: {s.note[:200]})' if s.note else ''))
        sm = next((m for m in mapped.scenes if m.scene_id == sid), None)
        for m in (sm.changes if sm else []):
            out.append(f'  change: "{m.quote[:120]}" -- {m.note[:200]}')
        for m in (sm.keeps if sm else []):
            out.append(f'  keep: "{m.quote[:120]}"')
    if mapped.already_used:
        out.append(f'{mapped.already_used} comment(s) an earlier run on PR #{pr} acted on, '
                   f'left out (named below)')
    if mapped.before_since:
        out.append(f'{mapped.before_since} comment(s) made before --since, left out (named '
                   f'below)')
    for why in mapped.left_out:
        out.append(f'Left out: {why}')
    for g in mapped.general:
        out.append(f'General comment (not sent; it isn\'t tied to a line): {g[:300]}')
    return out
