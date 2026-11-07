"""Reading level: Flesch-Kincaid grade per scene and for the scenes in scope.

A measure, not a craft principle: it has no 1-5 score and never enters the
scene averages or craft weights. `score` writes it to each scoring cycle
(`readability.csv`) and `score --readability` prints it without a cycle or
an API call. When storyforge.yaml sets `project.reading_level` (a grade,
`6`, or a range, `5-7`), each scene and the pooled figure are reported
against it. Prose projects only: graphic-novel scoring has no reading level.

Pure stdlib. Syllables are counted by vowel groups, with the silent endings
taken off ("-e", "-ed" and "-es", but not "-ted"/"-ded" or "-ses"/"-ches"
and the like, which are spoken). Every paragraph break ends a sentence, so
short dialogue lines count as sentences. It reads lower than the common
online Flesch-Kincaid calculators (*The Great Gatsby*: 5.9 here, about 7
there) but is consistent: compare like with like, and set a target on this
scale. Illustration markers are stripped
(`read_scene_prose`); quoted dialogue is split out for the narration's grade.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Literal, NamedTuple

from storyforge.illustrations import strip_markers
from storyforge.prose_analysis import dialogue_spans

#: a word: letters, joined by apostrophes or hyphens ("didn't", "wide-winged")
_WORD_RE = re.compile(r"[A-Za-z]+(?:['’\-][A-Za-z]+)*")
#: a sentence ends at . ! ? (and any closing quotes or brackets), then space
_SENTENCE_END_RE = re.compile(r'(?<=[.!?])["\'”’)\]]*\s+')
#: a markdown heading line or a scene break (`***`, `* * *`, `---`, `#`)
_NON_PROSE_LINE_RE = re.compile(r'^\s*(#.*|[*\-_](\s*[*\-_]){2,}|#)\s*$', re.MULTILINE)
#: a silent final "-e", "-ed" or "-es" after a consonant other than l or y
#: ("table" keeps its "-le"); `_SPOKEN_END_RE` excepts the spoken ones
_SILENT_END_RE = re.compile(r'(?:[^laeiouy]es|[^laeiouy]ed|[^laeiouy]e)$')
#: "-ted"/"-ded" ("wanted") and "-es" after a sibilant ("boxes", "wishes",
#: "faces", "pages") are a syllable of their own
_SPOKEN_END_RE = re.compile(r'(?:[td]ed|(?:[sxzc]|ch|sh|g)es)$')
_VOWEL_GROUP_RE = re.compile(r'[aeiouy]{1,2}')


def count_syllables(word: str) -> int:
    """Syllables in one word, by vowel groups; a hyphenated word is the sum
    of its parts. 0 for a word with no letters."""
    parts = [p for p in word.lower().split('-') if p]
    if len(parts) > 1:
        return sum(count_syllables(p) for p in parts)
    w = re.sub(r'[^a-z]', '', word.lower())
    if not w:
        return 0
    if len(w) <= 3:
        return 1
    if not _SPOKEN_END_RE.search(w):
        w = _SILENT_END_RE.sub('', w)
    w = re.sub(r'^y', '', w)
    return max(1, len(_VOWEL_GROUP_RE.findall(w)))


def _clean(text: str) -> str:
    """Prose only: a BOM, headings and scene breaks dropped, emphasis marks
    removed, line endings LF."""
    text = text.lstrip('﻿').replace('\r\n', '\n')
    text = _NON_PROSE_LINE_RE.sub('', text)
    return re.sub(r'[*_]+', '', text)


def split_sentences(text: str) -> list[str]:
    """The sentences of `text`, each holding at least one word. A paragraph
    break ends a sentence even without closing punctuation."""
    out = []
    for para in re.split(r'\n\s*\n', _clean(text)):
        for sent in _SENTENCE_END_RE.split(para.strip()):
            if _WORD_RE.search(sent):
                out.append(sent.strip())
    return out


def narration_text(text: str) -> str:
    """`text` with its quoted dialogue taken out. A quote that ended its
    sentence leaves the sentence break behind, so the narration on either
    side of it isn't read as one sentence; what's left of an attribution
    ("he said,") is a short sentence of its own."""
    text = strip_markers(text)
    out, pos = [], 0
    for start, end, inner in dialogue_spans(text):
        out.append(text[pos:start])
        out.append('.\n\n' if re.search(r'[.!?]\W*$', inner) else ' ')
        pos = end
    out.append(text[pos:])
    return ''.join(out)


@dataclass(frozen=True)
class Readability:
    """Counts for a stretch of prose and the grade they give. Counts add
    (`+`); grades are always computed from counts, never averaged."""
    words: int
    sentences: int
    syllables: int

    @property
    def words_per_sentence(self) -> float | None:
        return self.words / self.sentences if self.sentences else None

    @property
    def syllables_per_word(self) -> float | None:
        return self.syllables / self.words if self.words else None

    @property
    def grade(self) -> float | None:
        """Flesch-Kincaid grade level; None for text with no words."""
        if not self.words or not self.sentences:
            return None
        return (0.39 * self.words / self.sentences
                + 11.8 * self.syllables / self.words - 15.59)

    def __add__(self, other: object) -> 'Readability':
        if not isinstance(other, Readability):
            return NotImplemented
        return Readability(self.words + other.words, self.sentences + other.sentences,
                           self.syllables + other.syllables)


EMPTY = Readability(0, 0, 0)


def measure(text: str) -> Readability:
    """Words, sentences and syllables in `text`."""
    sentences = split_sentences(text)
    words = [w for s in sentences for w in _WORD_RE.findall(s)]
    return Readability(len(words), len(sentences), sum(count_syllables(w) for w in words))


@dataclass(frozen=True)
class SceneReadability:
    """One scene's readability: the `whole` scene and its `narration`
    (quoted dialogue taken out, `narration_text`)."""
    scene_id: str
    whole: Readability
    narration: Readability


def measure_scene(scene_id: str, text: str) -> SceneReadability:
    return SceneReadability(scene_id, measure(text), measure(narration_text(text)))


Verdict = Literal['', 'below', 'within', 'above']


class ReadingTarget(NamedTuple):
    """`project.reading_level` as grades, `low <= high` (one grade: equal)."""
    low: float
    high: float

    def verdict(self, grade: float | None) -> Verdict:
        """'below', 'within' (bounds included) or 'above'; '' with no grade."""
        if grade is None:
            return ''
        if grade < self.low:
            return 'below'
        if grade > self.high:
            return 'above'
        return 'within'

    def __str__(self) -> str:
        if self.low == self.high:
            return f'grade {self.low:g}'
        return f'grade {self.low:g}-{self.high:g}'


_NUM = r'\d+(?:\.\d+)?'


def parse_target(value: str) -> ReadingTarget | None:
    """`project.reading_level` as a ReadingTarget: `6` (or `6th`, `grade 6`)
    is 6-6, `5-7` (or `5–7`, `grade 5 to 7`, `7-5`) is 5-7. None when unset
    (empty, `null` or `~`).

    Raises:
        ValueError: set, but not a grade or a range of grades.
    """
    value = (value or '').strip()
    if value.lower() in ('', 'null', '~'):
        return None
    m = re.fullmatch(rf'(?:grades?\s*)?({_NUM})(?:st|nd|rd|th)?'
                     rf'(?:\s*(?:-|–|—|to)\s*({_NUM})(?:st|nd|rd|th)?)?',
                     value, flags=re.I)
    if not m:
        raise ValueError(f'project.reading_level is {value!r}: give a grade (6) '
                         'or a range of grades (5-7)')
    low, high = float(m.group(1)), float(m.group(2) or m.group(1))
    return ReadingTarget(min(low, high), max(low, high))


def read_target(project_dir: str) -> ReadingTarget | None:
    """The project's reading-level target (see `parse_target`)."""
    from storyforge.common import read_yaml_field
    return parse_target(read_yaml_field('project.reading_level', project_dir))


def verdict(grade: float | None, target: ReadingTarget | None) -> Verdict:
    """The target's verdict on `grade`; '' with no target."""
    return target.verdict(grade) if target is not None else ''


@dataclass
class Measured:
    """What `measure_scenes` found: the scenes measured, in order, and the
    ids it couldn't measure, each with why (no file, unreadable, no prose)."""
    rows: list[SceneReadability]
    unmeasured: dict[str, str]


def measure_scenes(scene_ids: list[str], project_dir: str) -> Measured:
    """Each scene's readability, in the order given. A scene with no file,
    one that can't be read or isn't UTF-8, and one with no words are
    `unmeasured`, for the caller to report, never skipped silently."""
    from storyforge.illustrations import read_scene_prose
    rows, unmeasured = [], {}
    for sid in scene_ids:
        path = os.path.join(project_dir, 'scenes', f'{sid}.md')
        if not os.path.isfile(path):
            unmeasured[sid] = 'no scene file'
            continue
        try:
            text = read_scene_prose(path)
        except (OSError, UnicodeDecodeError) as e:
            unmeasured[sid] = f"can't be read ({e.__class__.__name__})"
            continue
        scene = measure_scene(sid, text)
        if scene.whole.grade is None:
            unmeasured[sid] = 'no prose'
            continue
        rows.append(scene)
    return Measured(rows, unmeasured)


def pooled(rows: list[SceneReadability]) -> tuple[Readability, Readability]:
    """The scenes' pooled counts (whole, narration): every word and sentence
    counted once, not an average of scene grades. With every scene in
    scope, the book's."""
    whole, narration = EMPTY, EMPTY
    for r in rows:
        whole += r.whole
        narration += r.narration
    return whole, narration


def _fmt(x: float | None, places: int = 1) -> str:
    return '' if x is None else f'{x:.{places}f}'


#: `target_verdict` is '' with no target; the last row, `ALL`, pools the
#: scenes in scope (the whole book when no filter narrowed them)
CSV_HEADER = ('id|words|sentences|words_per_sentence|syllables_per_word|grade'
              '|narration_grade|target_verdict')
POOLED_ID = 'ALL'


def write_csv(path: str, rows: list[SceneReadability],
              target: ReadingTarget | None) -> None:
    """One row per measured scene and a final `ALL` row of pooled counts.
    LF line endings, like every CSV Storyforge writes."""
    whole, narration = pooled(rows)
    lines = [CSV_HEADER]
    for sid, a, n in ([(r.scene_id, r.whole, r.narration) for r in rows]
                      + [(POOLED_ID, whole, narration)]):
        lines.append('|'.join([
            sid, str(a.words), str(a.sentences), _fmt(a.words_per_sentence),
            _fmt(a.syllables_per_word, 2), _fmt(a.grade), _fmt(n.grade),
            verdict(a.grade, target)]))
    with open(path, 'w', encoding='utf-8', newline='') as f:
        f.write('\n'.join(lines) + '\n')


def summary_lines(measured: Measured, target: ReadingTarget | None) -> list[str]:
    """The pooled reading level, the scenes off the target, and the scenes
    that couldn't be measured."""
    rows = measured.rows
    whole, narration = pooled(rows)
    lines = []
    if whole.grade is None:
        lines.append('Reading level: no prose to measure')
    else:
        line = (f'Reading level: Flesch-Kincaid grade {whole.grade:.1f} '
                f'(narration {_fmt(narration.grade) or "n/a"}), '
                f'{whole.words_per_sentence:.1f} words a sentence, '
                f'{whole.words} words in {len(rows)} scene(s)')
        if target is None:
            lines.append(line + '; no target (set project.reading_level in storyforge.yaml)')
        else:
            lines.append(line + f'; target {target}: {target.verdict(whole.grade)}')
            for side in ('below', 'above'):
                off = [r for r in rows if target.verdict(r.whole.grade) == side]
                if off:
                    lines.append(f'  {len(off)} scene(s) {side} the target: '
                                 + ', '.join(f'{r.scene_id} ({_fmt(r.whole.grade)})'
                                             for r in off))
    if measured.unmeasured:
        lines.append(f'WARNING: reading level not measured for {len(measured.unmeasured)} '
                     'scene(s): ' + ', '.join(f'{sid} ({why})'
                                              for sid, why in measured.unmeasured.items()))
    return lines
