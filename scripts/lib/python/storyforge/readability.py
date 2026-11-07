"""Reading level: Flesch-Kincaid grade per scene and for the book.

A measure, not a craft principle: it has no 1-5 score and never enters the
scene averages or craft weights. `score` writes it to each cycle
(`readability.csv`) and `score --readability` prints it without a cycle or
an API call. When storyforge.yaml sets `project.reading_level` (a grade,
`6`, or a range, `5-7`), the book and each scene are reported against it.

Pure stdlib. Syllables are counted with the usual vowel-group heuristic,
so a grade is good to about half a grade, which is enough to steer by.
Illustration markers are stripped (`read_scene_prose`); quoted dialogue is
split out with `prose_analysis.extract_dialogue` for the narration's grade.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

from storyforge.prose_analysis import extract_dialogue

#: a word: letters, joined by apostrophes or hyphens ("didn't", "wide-winged")
_WORD_RE = re.compile(r"[A-Za-z]+(?:['’\-][A-Za-z]+)*")
#: a sentence ends at . ! ? (and any closing quotes or brackets), then space
_SENTENCE_END_RE = re.compile(r'(?<=[.!?])["\'”’)\]]*\s+')
#: a markdown heading line or a scene break (`***`, `* * *`, `---`, `#`)
_NON_PROSE_LINE_RE = re.compile(r'^\s*(#.*|[*\-_](\s*[*\-_]){2,}|#)\s*$', re.MULTILINE)
#: an unpronounced ending: "-es", "-ed" or "-e" after a consonant other than l
_SILENT_END_RE = re.compile(r'(?:[^laeiouy]es|[^laeiouy]ed|[^laeiouy]e)$')
_VOWEL_GROUP_RE = re.compile(r'[aeiouy]{1,2}')


def count_syllables(word: str) -> int:
    """Syllables in one word, by vowel groups; a hyphenated word is the sum
    of its parts. 0 for a word with no letters."""
    parts = [p for p in re.split(r'[\-]', word.lower()) if p]
    if len(parts) > 1:
        return sum(count_syllables(p) for p in parts)
    w = re.sub(r'[^a-z]', '', word.lower())
    if not w:
        return 0
    if len(w) <= 3:
        return 1
    w = _SILENT_END_RE.sub('', w)
    w = re.sub(r'^y', '', w)
    return max(1, len(_VOWEL_GROUP_RE.findall(w)))


def _clean(text: str) -> str:
    """Prose only: headings and scene breaks dropped, emphasis marks removed."""
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


@dataclass(frozen=True)
class Readability:
    """Counts for a stretch of prose and the grade they give."""
    words: int
    sentences: int
    syllables: int

    @property
    def words_per_sentence(self) -> float:
        return self.words / self.sentences if self.sentences else 0.0

    @property
    def syllables_per_word(self) -> float:
        return self.syllables / self.words if self.words else 0.0

    @property
    def grade(self) -> float | None:
        """Flesch-Kincaid grade level; None for text with no words."""
        if not self.words or not self.sentences:
            return None
        return (0.39 * self.words_per_sentence
                + 11.8 * self.syllables_per_word - 15.59)

    def __add__(self, other: 'Readability') -> 'Readability':
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
    scene_id: str
    all: Readability
    narration: Readability


def measure_scene(scene_id: str, text: str) -> SceneReadability:
    """The whole scene and its narration (quoted dialogue removed)."""
    _dialogue, narration = extract_dialogue(text)
    return SceneReadability(scene_id, measure(text), measure(narration))


def parse_target(value: str) -> tuple[float, float] | None:
    """`project.reading_level` as (low, high) grades: `6` is (6, 6), `5-7`
    (or `5–7`, `grade 5 to 7`) is (5, 7). None when unset.

    Raises:
        ValueError: set, but not a grade or a range of grades.
    """
    value = (value or '').strip()
    if not value:
        return None
    nums = re.findall(r'\d+(?:\.\d+)?', value)
    rest = re.sub(r'\d+(?:\.\d+)?|grades?|to|[\s\-–—]', '', value, flags=re.I)
    if not 1 <= len(nums) <= 2 or rest:
        raise ValueError(f'project.reading_level is {value!r}: give a grade (6) '
                         'or a range of grades (5-7)')
    low, high = float(nums[0]), float(nums[-1])
    return (min(low, high), max(low, high))


def verdict(grade: float | None, target: tuple[float, float] | None) -> str:
    """'below', 'within' or 'above' the target; '' with no target or grade."""
    if target is None or grade is None:
        return ''
    if grade < target[0]:
        return 'below'
    if grade > target[1]:
        return 'above'
    return 'within'


def read_target(project_dir: str) -> tuple[float, float] | None:
    """The project's reading-level target (see `parse_target`)."""
    from storyforge.common import read_yaml_field
    return parse_target(read_yaml_field('project.reading_level', project_dir))


def measure_scenes(scene_ids: list[str], project_dir: str
                   ) -> tuple[list[SceneReadability], list[str]]:
    """Each scene's readability, in the order given, and the ids with no
    scene file (reported by the caller, not skipped silently)."""
    from storyforge.illustrations import read_scene_prose
    rows, missing = [], []
    for sid in scene_ids:
        path = os.path.join(project_dir, 'scenes', f'{sid}.md')
        if not os.path.isfile(path):
            missing.append(sid)
            continue
        rows.append(measure_scene(sid, read_scene_prose(path)))
    return rows, missing


def book_totals(rows: list[SceneReadability]) -> tuple[Readability, Readability]:
    """The book's pooled counts (all, narration): every word and sentence
    counted once, not an average of scene grades."""
    total, narration = EMPTY, EMPTY
    for r in rows:
        total += r.all
        narration += r.narration
    return total, narration


def _fmt(grade: float | None) -> str:
    return '' if grade is None else f'{grade:.1f}'


CSV_HEADER = ('id|words|sentences|words_per_sentence|syllables_per_word|grade'
              '|narration_grade|target_verdict')


def write_csv(path: str, rows: list[SceneReadability],
              target: tuple[float, float] | None) -> None:
    """One row per scene and a final `BOOK` row with the pooled counts."""
    total, narration = book_totals(rows)
    lines = [CSV_HEADER]
    for sid, a, n in ([(r.scene_id, r.all, r.narration) for r in rows]
                      + [('BOOK', total, narration)]):
        lines.append('|'.join([
            sid, str(a.words), str(a.sentences), f'{a.words_per_sentence:.1f}',
            f'{a.syllables_per_word:.2f}', _fmt(a.grade), _fmt(n.grade),
            verdict(a.grade, target)]))
    with open(path, 'w', encoding='utf-8', newline='') as f:
        f.write('\n'.join(lines) + '\n')


def format_target(target: tuple[float, float] | None) -> str:
    if target is None:
        return ''
    low, high = target
    g = lambda x: f'{x:g}'
    return f'grade {g(low)}' if low == high else f'grade {g(low)}-{g(high)}'


def summary_lines(rows: list[SceneReadability],
                  target: tuple[float, float] | None) -> list[str]:
    """The book's reading level, and against the target which scenes are off."""
    total, narration = book_totals(rows)
    if total.grade is None:
        return ['Reading level: no prose to measure']
    line = (f'Reading level: Flesch-Kincaid grade {total.grade:.1f} '
            f'(narration {_fmt(narration.grade) or "n/a"}), '
            f'{total.words_per_sentence:.1f} words a sentence, '
            f'{total.words} words in {len(rows)} scene(s)')
    if target is None:
        return [line + '; no target (set project.reading_level in storyforge.yaml)']
    lines = [line + f'; target {format_target(target)}: {verdict(total.grade, target)}']
    for side in ('below', 'above'):
        off = [r for r in rows if verdict(r.all.grade, target) == side]
        if off:
            lines.append(f'  {len(off)} scene(s) {side} the target: '
                         + ', '.join(f'{r.scene_id} ({_fmt(r.all.grade)})' for r in off))
    return lines
