"""Extraction's act step: the book's three acts, decided once for the whole book.

Phase 1 asks every scene for its act on its own, with no view of the rest of
the book, so the answers flip back and forth: on all 13 evals books the act
steps backwards somewhere as seq rises (F-160). Acts are contiguous runs of
scenes in reading order, so they are decided here, in one call that sees
every scene, and written over phase 1's per-scene answers. When the call
fails, the per-scene answers are fitted to the closest contiguous split
instead, so the column is never left out of order.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable

from .common import log

ACT_COUNT = 3
OPENING_WORDS = 40


@dataclass(frozen=True)
class ActsResult:
    source: str                  # 'model', 'votes' (the fallback) or 'none'
    starts: list[str]            # the first scene id of each act, in order
    changed: int                 # scenes whose act changed
    note: str = ''               # why the fallback was used


class ActsProblems(ValueError):
    def __init__(self, problems: list[str]):
        super().__init__('; '.join(problems))
        self.problems = problems


def _schema() -> dict:
    from .extract import _object, _STR
    return _object({'acts': {'type': 'array', 'items': _object({
        'first_scene': _STR, 'last_scene': _STR, 'title': _STR, 'reason': _STR})}})


ACTS_SCHEMA = _schema()


INACTIVE = frozenset({'cut', 'merged'})


def _seq(row: dict[str, str]) -> float:
    """A row's seq for sorting; one with no number sorts last."""
    try:
        return float(row.get('seq', '').strip())
    except ValueError:
        return float('inf')


def in_order(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return sorted(rows, key=_seq)


def backward_steps(rows: list[dict[str, str]]) -> list[tuple[str, str]]:
    """(earlier id, later id) for every place where the act number goes down
    as seq rises. Rows with no numeric act are skipped over."""
    steps, prev = [], None
    for row in in_order(rows):
        act = row.get('act', '').strip()
        if not act.isdecimal():
            continue
        if prev and int(act) < int(prev[1]):
            steps.append((prev[0], row['id']))
        prev = (row['id'], act)
    return steps


def fit_votes(votes: list[str], n: int = ACT_COUNT) -> list[int]:
    """The contiguous split into acts 1..n (each act non-empty) that agrees
    with the most per-scene votes. A vote that isn't a number agrees with
    nothing. Fewer scenes than acts: one act per scene."""
    m = len(votes)
    if m == 0:
        return []
    if m < n:
        return list(range(1, m + 1))
    agree = [[1 if v.strip() == str(a) else 0 for v in votes] for a in range(1, n + 1)]
    # best[a][i]: most agreements putting votes[:i] in acts 1..a (each non-empty)
    neg = -1
    best = [[neg] * (m + 1) for _ in range(n + 1)]
    cut = [[0] * (m + 1) for _ in range(n + 1)]
    best[0][0] = 0
    for a in range(1, n + 1):
        for i in range(a, m - (n - a) + 1):
            run = 0
            for j in range(i - 1, a - 2, -1):     # act a covers votes[j:i]
                run += agree[a - 1][j]
                if best[a - 1][j] != neg and best[a - 1][j] + run > best[a][i]:
                    best[a][i], cut[a][i] = best[a - 1][j] + run, j
    acts, i = [0] * m, m
    for a in range(n, 0, -1):
        j = cut[a][i]
        acts[j:i] = [a] * (i - j)
        i = j
    return acts


def _opening(scenes_dir: str, sid: str) -> str:
    path = os.path.join(scenes_dir, f'{sid}.md')
    if not os.path.isfile(path):
        return ''
    with open(path, encoding='utf-8') as f:
        words = f.read().split()
    text = ' '.join(words[:OPENING_WORDS])
    return text + (' …' if len(words) > OPENING_WORDS else '')


def _first_line(scenes_dir: str, sid: str) -> str:
    path = os.path.join(scenes_dir, f'{sid}.md')
    if not os.path.isfile(path):
        return ''
    with open(path, encoding='utf-8') as f:
        lines = f.read().lstrip('\ufeff').splitlines()
    if lines and lines[0].rstrip() == '---':            # frontmatter
        close = next((i for i, line in enumerate(lines[1:], 1) if line.rstrip() == '---'),
                     len(lines))
        lines = lines[close + 1:]
    return next((line for line in lines if line.strip()), '')


def divisions(ref_dir: str, scenes_dir: str, scenes: list[dict[str, str]]) -> dict[str, str]:
    """Where the printed book's divisions begin: scene id -> what it opens
    ("part 2; Chapter XII"). Chapters come from `chapter-map.csv`, or else
    from the headings at the top of scenes ("# Stave I"); parts from where
    `scenes.csv:part` changes (F-162: in an epic the act turns fall at the
    printed books' openings, which the act call couldn't see)."""
    from .elaborate import _read_csv
    from .extract_describe import _CHAPTER_HEADING
    ids = {r['id'] for r in scenes}
    chapters: dict[str, str] = {}
    for row in _read_csv(os.path.join(ref_dir, 'chapter-map.csv')):
        first = next((s.strip() for s in row.get('scenes', '').split(';') if s.strip() in ids),
                     '')
        if first:
            chapters.setdefault(first, row.get('title', '').strip()
                                or f'chapter {row.get("chapter", "").strip()}')
    if not chapters:
        for r in scenes:
            m = _CHAPTER_HEADING.match(_first_line(scenes_dir, r['id']))
            if m:
                chapters[r['id']] = m.group(1).strip()
    marks, prev = {}, None
    for r in scenes:
        part = r.get('part', '').strip()
        bits = []
        if part and part != prev:
            bits.append(f'part {part}')
        prev = part or prev
        if r['id'] in chapters:
            bits.append(chapters[r['id']])
        if bits:
            marks[r['id']] = '; '.join(bits)
    return marks


def build_acts_prompt(profile: dict[str, str], scenes: list[dict[str, str]],
                      scenes_dir: str, problems: list[str] | None = None,
                      marks: dict[str, str] | None = None) -> str:
    marks = marks or {}
    lines = []
    for row in scenes:
        summary = row.get('summary', '').strip()
        what = summary if summary else f'opens: {_opening(scenes_dir, row["id"])}'
        if row['id'] in marks:
            lines.append(f'[{marks[row["id"]]} begins]')
        lines.append(f'{row.get("seq", "")}. {row["id"]} | {row.get("title", "").strip()} '
                     f'| {what}')
    divisions_note = ('''
Lines in [brackets] mark where the printed book's parts and chapters begin.
A turn often falls at one of them, so when the turn you see is near a
division, check whether the act begins there; an act that begins inside a
chapter should have a reason in the text. A single event (a death and its
aftermath, a battle) belongs to one act.
''' if marks else '')
    retry = ''
    if problems:
        retry = ('\n## Your previous answer could not be used\n\n'
                 + '\n'.join(f'- {p}' for p in problems)
                 + '\n\nAnswer again with these fixed.\n')
    return f"""Divide this book into its {ACT_COUNT} acts.

An act is a run of consecutive scenes in reading order: every scene belongs to
exactly one act, and the acts never interleave. Act 1 sets up the situation
and ends at the turn that commits the story to its central conflict. Act 2
develops and complicates that conflict. Act 3 begins at the turn that sets up
the resolution and runs to the end. These are the book's dramatic acts, not
its printed parts, volumes or books, which may or may not line up with them.
Judge where the turns fall from what happens, not from how many scenes each
act gets: acts are often uneven.
{divisions_note}
## What a first reading of the book noted

- Narrative mode: {profile.get('narrative_mode', 'unknown')}
- Central conflict: {profile.get('central_conflict', 'unknown')}
- Protagonist arc: {profile.get('protagonist_arc', 'unknown')}
- Structure: {profile.get('act_structure', 'unknown')}

The structure note may count movements or parts rather than {ACT_COUNT} acts,
and its scene numbers were estimates; the scene list below is the real one.

## The scenes, in reading order (seq. id | title | summary or opening words)

{chr(10).join(lines)}
{retry}
## Answer

`acts`: exactly {ACT_COUNT} entries, in order. For each act, `first_scene` and
`last_scene` are the ids of its first and last scenes: act 1 begins with the
first scene above (`{scenes[0]['id']}`), each later act begins with the scene
right after the previous act's last scene, and act {ACT_COUNT} ends with the last
scene (`{scenes[-1]['id']}`). `title` names the act in a few words, and `reason`
says in one sentence what turn opens it, which happens in its `first_scene`."""


def parse_acts(reply: str, scenes: list[dict[str, str]]) -> list[str]:
    """The first scene id of each act. Raises ActsProblems when the answer
    can't be used as it is, ValueError when it can't be read."""
    from .extract import _json_answer
    data = _json_answer(reply, ACTS_SCHEMA)
    order = {row['id']: i for i, row in enumerate(scenes)}
    starts = [str(a.get('first_scene', '')).strip() for a in data['acts']]
    ends = [str(a.get('last_scene', '')).strip() for a in data['acts']]
    problems = []
    if len(starts) != ACT_COUNT:
        problems.append(f'acts has {len(starts)} entries; expected exactly {ACT_COUNT}')
    unknown = [s for s in starts + ends if s not in order]
    if unknown:
        problems.append('first_scene/last_scene name scene(s) not in the list: '
                        + ', '.join(repr(s) for s in unknown))
    if not problems:
        seq = lambda sid: scenes[order[sid]].get('seq', '?')
        if starts[0] != scenes[0]['id']:
            problems.append(f"act 1 must begin with the first scene, {scenes[0]['id']!r}, "
                            f'not {starts[0]!r}')
        if ends[-1] != scenes[-1]['id']:
            problems.append(f"act {ACT_COUNT} must end with the last scene, "
                            f"{scenes[-1]['id']!r}, not {ends[-1]!r}")
        for n, (first, last) in enumerate(zip(starts, ends), 1):
            if order[last] < order[first]:
                problems.append(f'act {n} ends ({last}, seq {seq(last)}) before it begins '
                                f'({first}, seq {seq(first)})')
        # Each act must begin right after the one before ends. A gap or an
        # overlap means an id doesn't match the turn the answer describes
        # (Five Weeks: act 2's reason was the launch, its first_scene 75 scenes later)
        for n in range(1, len(starts)):
            last, first = ends[n - 1], starts[n]
            if order[first] != order[last] + 1:
                problems.append(
                    f'act {n} ends at {last} (seq {seq(last)}) but act {n + 1} begins at '
                    f'{first} (seq {seq(first)}): each act must begin with the scene right '
                    f'after the previous act ends. Check which scene the turn you describe '
                    f'happens in')
    if problems:
        raise ActsProblems(problems)
    return starts


def assign(scenes: list[dict[str, str]], starts: list[str]) -> list[int]:
    """Each scene's act number, from the acts' first scenes."""
    first = {sid: i for i, sid in enumerate(starts, 1)}
    acts, act = [], 1
    for row in scenes:
        act = first.get(row['id'], act)
        acts.append(act)
    return acts


def _ask_model(scenes, scenes_dir, profile, model, log_dir, on_usage,
               marks=None) -> list[str]:
    from .api import extract_text, invoke_to_file, is_truncated
    problems = None
    for attempt in (1, 2):
        log_file = os.path.join(log_dir, f'extract-acts-{attempt}.json')
        response = invoke_to_file(build_acts_prompt(profile, scenes, scenes_dir, problems, marks),
                                  model, log_file, 2048, label='acts',
                                  output_schema=ACTS_SCHEMA)
        if on_usage:
            on_usage(log_file, 'extract-acts', 'book', model)
        if is_truncated(response):
            raise ValueError('the reply hit its token limit')
        try:
            return parse_acts(extract_text(response), scenes)
        except ActsProblems as e:
            if attempt == 2:
                raise
            log(f'  acts: {len(e.problems)} problem(s) in the reply; asking once more')
            problems = e.problems
    raise AssertionError('unreachable')


def run_acts(ref_dir: str, scenes_dir: str, log_dir: str, profile: dict[str, str],
             model: str, on_usage: Callable | None = None) -> ActsResult:
    """Decide the book's acts and write them to `scenes.csv:act`."""
    from .elaborate import _read_csv, _write_csv
    path = os.path.join(ref_dir, 'scenes.csv')
    rows = _read_csv(path)
    if not rows:
        return ActsResult('none', [], 0, 'scenes.csv has no scenes')
    with open(path, encoding='utf-8') as f:
        columns = f.readline().rstrip('\r\n').lstrip('﻿').split('|')
    if 'act' not in columns:
        columns.append('act')
    # Cut and merged scenes aren't in the book: they keep their act and
    # aren't shown to the model or counted in the fit
    scenes = [r for r in in_order(rows)
              if r.get('status', '').strip().lower() not in INACTIVE]
    if not scenes:
        return ActsResult('none', [], 0, 'every scene is cut or merged')
    votes = [r.get('act', '') for r in scenes]

    source, note = 'model', ''
    if len(scenes) < ACT_COUNT:
        acts, source, note = fit_votes(votes), 'votes', f'fewer than {ACT_COUNT} scenes'
    else:
        try:
            starts = _ask_model(scenes, scenes_dir, profile, model, log_dir, on_usage,
                                divisions(ref_dir, scenes_dir, scenes))
            acts = assign(scenes, starts)
        except (RuntimeError, ValueError, OSError) as e:   # API error, refusal, unusable reply
            note = f'the act call failed ({e})'
            if not any(v.strip() in {str(a) for a in range(1, ACT_COUNT + 1)} for v in votes):
                log(f'  WARNING: {note}, and no scene has an act to fit; acts left as they were')
                return ActsResult('none', [], 0, note)
            log(f'  WARNING: {note}; fitting the per-scene acts to the closest '
                'contiguous split instead')
            acts, source = fit_votes(votes), 'votes'

    changed = 0
    for row, act in zip(scenes, acts):
        if row.get('act', '').strip() != str(act):
            changed += 1
        row['act'] = str(act)
    _write_csv(path, rows, columns)
    starts = [row['id'] for i, (row, act) in enumerate(zip(scenes, acts))
              if i == 0 or acts[i - 1] != act]
    return ActsResult(source, starts, changed, note)
