"""The voiceprint's described voice and exemplar shortlist (plan B3, B4, #651).

A model reads a large sample of the author's corpus alongside the
fingerprint (`storyforge.voiceprint`) and proposes two things, which the
author then corrects. Everything lives in the author voice repo (plan B0):

- **The described voice (B3).** Short claims, each one sentence, in
  `SECTIONS`: what the voice does and never does, its stance toward the
  reader, its humour, its rhythm. They go to `proposals/description-claims.csv`
  (`CLAIM_COLUMNS`) with an empty `mark` column. The author marks each claim
  `yes` ("yes, me") or `no`, and may reword one before marking it yes.
  `accept_description` writes the claims marked yes to `description.md`; an
  unmarked claim or a mark that isn't yes or no stops it, nothing written.
- **The exemplar shortlist (B4).** The model names runs of consecutive
  paragraphs in the sample (by the numbers the sample shows), 100 to 400
  words each, tagged by job (`JOBS`). The code cuts each passage from the
  corpus as written (the model never copies text), refuses a run that is out
  of the sample, crosses a passage break, overlaps another or is the wrong
  length (each refusal named), and measures each against the fingerprint
  (`passage_range`: `typical` when its distance is inside the corpus's own
  range for passages of its size). They go to `proposals/shortlist.csv`
  (`SHORTLIST_COLUMNS`) and `proposals/shortlist/<id>.md`, with an empty
  `pick` column. The author writes `yes` in `pick` for each passage to keep
  (and may trim its file), and `accept_exemplars` copies the picks to
  `exemplars/<id>.md` with their index `exemplars/exemplars.csv`
  (`EXEMPLAR_COLUMNS`). `auto_picks` is the rule the reference voiceprint's
  exemplars were chosen by (no author to pick them): every typical passage,
  topped up to `SHORTLIST_MIN` with the nearest of the rest.

The two model calls send the same system block (the sample and the
fingerprint) but no cache mark: their structured-output schemas differ, and
the schema is part of the cached prefix, so a cache written by one is never
read by the other (measured on the first Austen recording: each call wrote
the whole block, at 1.25 times the input price). The sample is `SAMPLE_WINDOWS` runs of about `voiceprint.CHUNK_WORDS` words,
evenly spaced through the fingerprinted corpus (the pieces
`fingerprint.json` names). Neither prompt names the author: the claims have
to come from the text.

API: `load_voice(voice_dir)` -> `Voice`; `build_sample(texts)` -> `Sample`;
`system_blocks(voice, sample)`, `description_prompt()`, `shortlist_prompt()`;
`propose_description(...)` / `propose_shortlist(...)` (one call each, through
`storyforge.api`); `parse_claims(reply)`, `parse_shortlist(reply, sample)`;
`write_claims` / `read_claims`, `write_shortlist` / `read_shortlist`;
`accept_description`, `accept_exemplars`; `recorded_sample(system_text, texts)`
(a recorded reply parsed as it was answered); `rejudge`; `passage_range(fp, texts)` ->
`PassageRange`; `auto_picks(rows)`; `forecast(voice, sample, model)`.
Errors are `ProposalError`, whose message says what to fix. The CLI is
`storyforge voice propose` / `judge` / `accept` (`cmd_voice`).
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field, replace
from typing import Mapping, Sequence

from storyforge import voiceprint as vp
from storyforge.common import csv_safe

#: the description's sections, in the order description.md gives them
SECTIONS = ('does', 'never', 'stance', 'humour', 'rhythm')
SECTION_HEADINGS = {
    'does': 'What the voice does',
    'never': 'What it never does',
    'stance': 'Its stance toward the reader',
    'humour': 'Its humour',
    'rhythm': 'Its rhythm',
}
#: what an exemplar passage is for
JOBS = ('description', 'argument', 'turn', 'humour', 'quiet', 'dialogue')
#: an exemplar's length, in words (plan B4)
PASSAGE_MIN, PASSAGE_MAX = 100, 400
#: the shortlist's size (plan B4) and how many passages the model is asked for
SHORTLIST_MIN, SHORTLIST_MAX = 20, 40
SHORTLIST_ASK = 30
#: the sample: this many runs of about `voiceprint.CHUNK_WORDS` words
SAMPLE_WINDOWS = 15
#: answer budgets (thinking is added by `api.request_max_tokens`)
DESCRIPTION_TOKENS = 4000
SHORTLIST_TOKENS = 6000
#: the model task (`common.select_model`): judgment over a large sample
MODEL_TASK = 'synthesis'

MARKS = ('yes', 'no')
PROPOSALS_DIR = 'proposals'
CLAIMS_FILE = os.path.join(PROPOSALS_DIR, 'description-claims.csv')
SHORTLIST_FILE = os.path.join(PROPOSALS_DIR, 'shortlist.csv')
SHORTLIST_DIR = os.path.join(PROPOSALS_DIR, 'shortlist')
DESCRIPTION_FILE = 'description.md'
EXEMPLARS_DIR = 'exemplars'
EXEMPLARS_INDEX = os.path.join(EXEMPLARS_DIR, 'exemplars.csv')
FINGERPRINT_FILE = 'fingerprint.json'
VOICE_FILE = 'voice.yaml'
#: where `propose` keeps each raw reply before parsing it (a paid reply is
#: never lost to a parse failure)
REPLIES_DIR = os.path.join('working', 'voice-replies')

CLAIM_COLUMNS = ('id', 'section', 'claim', 'example', 'mark')
SHORTLIST_COLUMNS = ('id', 'job', 'source', 'paragraphs', 'words', 'distance', 'limit',
                     'typical', 'why', 'pick')
EXEMPLAR_COLUMNS = ('id', 'job', 'source', 'paragraphs', 'words', 'why')


class ProposalError(Exception):
    """A proposal that can't be made, read or accepted; the message says why."""


# ============================================================================
# The voice repo
# ============================================================================

@dataclass(frozen=True)
class Voice:
    """An author voice repo: its directory, author name (voice.yaml's
    `author`, '' when it has none), fingerprint, and the fingerprinted
    corpus by the names `fingerprint.json` gives its pieces."""
    path: str
    author: str
    fingerprint: vp.Fingerprint
    texts: dict[str, str]


def _read(path: str) -> str:
    with open(path, encoding='utf-8') as f:
        return f.read()


def _author(voice_dir: str) -> str:
    from storyforge.prompts import read_yaml_field   # (yaml_file, field)
    return read_yaml_field(os.path.join(voice_dir, VOICE_FILE), 'author')


def check_voice_dir(voice_dir: str) -> None:
    """Raise ProposalError unless `voice_dir` is an author voice repo: it
    has voice.yaml, and it isn't a book (no storyforge.yaml)."""
    if os.path.isfile(os.path.join(voice_dir, 'storyforge.yaml')):
        raise ProposalError(f'{voice_dir} is a book (it has storyforge.yaml); run this in '
                            f'the author voice repo')
    if not os.path.isfile(os.path.join(voice_dir, VOICE_FILE)):
        raise ProposalError(f'{voice_dir} has no {VOICE_FILE}: run this in the author '
                            f'voice repo')


def load_voice(voice_dir: str) -> Voice:
    """The voice repo with its fingerprint and fingerprinted corpus. Raises
    ProposalError when it isn't a voice repo, the fingerprint is missing or
    can't be read, or a piece the fingerprint names can't be read."""
    check_voice_dir(voice_dir)
    fp_path = os.path.join(voice_dir, FINGERPRINT_FILE)
    if not os.path.isfile(fp_path):
        raise ProposalError(f'{voice_dir} has no {FINGERPRINT_FILE}: compute the fingerprint '
                            f'first (references/voiceprints/README.md)')
    try:
        fp = vp.Fingerprint.load(fp_path)
    except vp.VoiceprintError as e:
        raise ProposalError(str(e)) from e
    names = [p.get('name', '') for p in fp.pieces]
    if not names or not all(names):
        raise ProposalError(f'{fp_path} names no corpus pieces, so the sample can\'t be '
                            f'taken from what was fingerprinted; compute it again from '
                            f'files by name (voiceprint.fingerprint({{path: text}}))')
    texts = {}
    for name in names:
        path = os.path.join(voice_dir, name)
        try:
            texts[name] = _read(path)
        except (OSError, UnicodeDecodeError) as e:
            raise ProposalError(f'{FINGERPRINT_FILE} names {name}, which can\'t be read '
                                f'({e})') from e
    return Voice(voice_dir, _author(voice_dir), fp, texts)


# ============================================================================
# The sample
# ============================================================================

@dataclass(frozen=True)
class Paragraph:
    """One prose paragraph of the sample: `number` is the sample's (1..),
    `index` its place among its piece's prose paragraphs (1..), `window`
    which of the sample's runs it is in."""
    number: int
    source: str
    index: int
    window: int
    text: str
    words: int


@dataclass(frozen=True)
class Sample:
    paragraphs: tuple[Paragraph, ...]
    windows: int

    @property
    def words(self) -> int:
        return sum(p.words for p in self.paragraphs)

    def get(self, number: int) -> Paragraph | None:
        if 1 <= number <= len(self.paragraphs):
            return self.paragraphs[number - 1]
        return None


def prose_paragraphs(text: str) -> list[str]:
    """`text`'s paragraphs as written (blank-line separated, the lines of one
    paragraph joined by a space), leaving out Markdown headings (`#`) and
    lines with no letter (scene breaks). Its own rule, not the
    fingerprint's (`voiceprint.paragraphs`, which also drops bare chapter
    titles and a letter's salutation): a passage's paragraph numbers and a
    recorded sample must stay put when the fingerprint's filter changes."""
    out = []
    for block in re.split(r'\n\s*\n', text.lstrip('\ufeff').replace('\r\n', '\n')):
        para = ' '.join(line.strip() for line in block.split('\n') if line.strip())
        if para and not para.startswith('#') and re.search(r'[^\W\d_]', para):
            out.append(para)
    return out


def _runs(paras: Sequence[str], size: int) -> list[list[int]]:
    """Consecutive runs of paragraph indexes of at least `size` words (a
    short last run is dropped), as `voiceprint.chunks` cuts."""
    out, cur, n = [], [], 0
    for i, p in enumerate(paras):
        cur.append(i)
        n += len(vp.words(p))
        if n >= size:
            out.append(cur)
            cur, n = [], 0
    if cur and n >= size / 2:
        out.append(cur)
    return out


def build_sample(texts: Mapping[str, str], windows: int = SAMPLE_WINDOWS,
                 size: int = vp.CHUNK_WORDS) -> Sample:
    """`windows` runs of about `size` words, evenly spaced through the
    corpus (each piece cut on its own, so no run crosses two pieces); all
    the runs when there are fewer. Paragraphs are numbered through the
    sample. Raises ProposalError for a corpus with no run."""
    runs = []
    for name, text in texts.items():
        paras = prose_paragraphs(text)
        runs += [(name, paras, run) for run in _runs(paras, size)]
    if not runs:
        raise ProposalError('the corpus has no prose to sample')
    if len(runs) > windows:
        picked = [runs[int((i + 0.5) * len(runs) / windows)] for i in range(windows)]
    else:
        picked = runs
    out = []
    for w, (name, paras, run) in enumerate(picked, start=1):
        for i in run:
            out.append(Paragraph(len(out) + 1, name, i + 1, w, paras[i],
                                 len(vp.words(paras[i]))))
    return Sample(tuple(out), len(picked))


def render_sample(sample: Sample) -> str:
    lines = []
    window = 0
    for p in sample.paragraphs:
        if p.window != window:
            window = p.window
            lines.append(f'\n## Passage {window} (from {p.source})\n')
        lines.append(f'[{p.number}, {p.words} words] {p.text}')
    return '\n'.join(lines).strip()


_WINDOW_RE = re.compile(r'^## Passage (\d+) \(from (.+)\)$')
_PARA_RE = re.compile(r'^\[(\d+), (\d+) words\] (.*)$')


def recorded_sample(system_text: str, texts: Mapping[str, str]) -> Sample:
    """The sample a recorded system block showed (`render_sample`'s lines),
    each paragraph found again in the corpus (`texts`) for its place in its
    piece: a recorded reply can then be parsed as it was answered, whatever
    the sampling or the fingerprint does now. Raises ProposalError when the
    block shows no sample, or a passage isn't in its piece as a run of
    paragraphs (the corpus changed since)."""
    windows: list[tuple[int, str, list[tuple[int, str]]]] = []
    for line in system_text.split('\n'):
        m = _WINDOW_RE.match(line)
        if m:
            windows.append((int(m.group(1)), m.group(2), []))
            continue
        m = _PARA_RE.match(line)
        if m and windows:
            windows[-1][2].append((int(m.group(1)), m.group(3)))
    if not windows:
        raise ProposalError('the recorded system block shows no sample')
    out = []
    for w, source, paras in windows:
        if source not in texts:
            raise ProposalError(f'the recorded sample\'s passage {w} is from {source}, '
                                f'which isn\'t in the corpus')
        corpus = prose_paragraphs(texts[source])
        want = [t for _, t in paras]
        start = next((i for i in range(len(corpus) - len(want) + 1)
                      if corpus[i:i + len(want)] == want), None)
        if start is None:
            raise ProposalError(f'the recorded sample\'s passage {w} isn\'t in {source} as '
                                f'it is now: the corpus changed since the recording')
        for k, (number, text) in enumerate(paras):
            if number != len(out) + 1:
                raise ProposalError(f'the recorded sample\'s paragraph [{number}] is out of '
                                    f'order')
            out.append(Paragraph(number, source, start + k + 1, w, text,
                                 len(vp.words(text))))
    return Sample(tuple(out), len(windows))


# ============================================================================
# The fingerprint, for the model
# ============================================================================

def _sig(x: float, digits: int = 2) -> str:
    """`x` to `digits` significant figures (coarse on purpose: the prompt
    shouldn't change with a measure's last decimal)."""
    if x == 0:
        return '0'
    return f'{float(f"{x:.{digits}g}"):g}'


#: function words shown to the model: the ones furthest from other writers
FUNCTION_WORDS_SHOWN = 12
NGRAMS_SHOWN = 15


def render_fingerprint(fp: vp.Fingerprint, baseline: vp.Baseline | None = None) -> str:
    """The fingerprint in words a model can use: each measure's value
    beside other writers' (the general baseline's population), with its z;
    the function words furthest from other writers; the sentence-length
    distribution; the phrases used more than other writers use them; the
    words paragraphs open on. Figures are rounded."""
    base = baseline or vp.load_baseline()

    def z(name):
        return (fp.stats[name].center - base.mean[name]) / base.sd[name]

    lines = [f'Measured over {fp.words:,} words in {fp.chunks} chunks of '
             f'{vp.CHUNK_WORDS:,}. Each measure is the median over the chunks (p10-p90 '
             f'the writer\'s typical range), beside the mean of a population of '
             f'other writers (28 public-domain books, 1719-1920); z is how many '
             f'population standard deviations the writer sits above (+) or below (-) '
             f'them. Rates are per 1,000 words; shares are fractions.', '']
    for group in vp.GROUPS:
        if group == 'function_words':
            continue
        lines.append(f'### {group}')
        for name in vp.measure_names():
            if vp.measure_group(name) != group:
                continue
            s = fp.stats[name]
            lines.append(f'- {name}: {_sig(s.center)} (typical {_sig(s.p10)}-{_sig(s.p90)}; '
                         f'other writers {_sig(base.mean[name])}; z {z(name):+.1f})')
        lines.append('')
    fws = sorted((n for n in vp.measure_names() if vp.measure_group(n) == 'function_words'),
                 key=lambda n: (-abs(z(n)), n))[:FUNCTION_WORDS_SHOWN]
    lines.append('### function words furthest from other writers (per 1,000 words)')
    for name in fws:
        lines.append(f'- {name.removeprefix("fw_")}: {_sig(fp.stats[name].center)} '
                     f'(other writers {_sig(base.mean[name])}; z {z(name):+.1f})')
    if fp.sentence_lengths:
        lines += ['', '### sentence lengths (share of sentences, by words)',
                  ', '.join(f'{k}: {round(100 * v)}%' for k, v in fp.sentence_lengths.items())]
    for n, grams in sorted(fp.ngrams.items()):
        if grams:
            lines += ['', f'### {n}-word phrases used more than other writers use them',
                      ', '.join(g[0] for g in grams[:NGRAMS_SHOWN])]
    if fp.first_words:
        lines += ['', '### words paragraphs most often open on',
                  ', '.join(fp.first_words)]
    return '\n'.join(lines).strip()


#: the system block's opening, part of the prompt (a change re-records)
SYSTEM_PREAMBLE = ('You are helping a writer see their own prose voice. Below are a sample of '
                   'their writing and the fingerprint measured over their corpus.')


def system_blocks(voice: Voice, sample: Sample,
                  baseline: vp.Baseline | None = None) -> list[dict]:
    """The system block both calls send: the sample, then the fingerprint.
    No temp path, date or author name in it, so a recording replays. Not
    marked for the cache (see the module docstring)."""
    text = (
        f'{SYSTEM_PREAMBLE}\n\n'
        f'# The sample\n\n{sample.windows} passages of about {vp.CHUNK_WORDS:,} words, '
        'evenly spaced through the corpus. Every paragraph is numbered through the '
        'sample, with its word count: [number, words].\n\n'
        f'{render_sample(sample)}\n\n'
        f'# The fingerprint\n\n{render_fingerprint(voice.fingerprint, baseline)}\n')
    return [{'type': 'text', 'text': text}]


# ============================================================================
# The described voice (B3)
# ============================================================================

DESCRIPTION_PROMPT = """\
Describe this writer's prose voice as a list of short claims the writer will mark one by one, "yes, that's me" or "no".

Sections:
- does: what the voice habitually does (6 to 10 claims)
- never: what it never, or almost never, does (3 to 6 claims)
- stance: its stance toward the reader (2 to 4 claims)
- humour: its humour, or its lack of humour (2 to 4 claims)
- rhythm: how its sentences and paragraphs move (2 to 4 claims)

Rules:
- One sentence a claim, in plain words, specific enough to be wrong. "Uses vivid language" says nothing; "Sentences often turn on a final qualifying clause" can be checked.
- Describe how the writer writes (the narration's habits, syntax, diction, stance), not the plot, the characters or the themes.
- Ground every claim in the sample and the fingerprint. Where the fingerprint shows a habit (a measure far from other writers), say what it looks like on the page.
- For each claim give one short example from the sample (under 25 words), copied exactly, that shows it; for a "never" claim give "".
- Don't name the writer, a book or a character in a claim."""

CLAIMS_SCHEMA = {
    'type': 'object',
    'properties': {
        'claims': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'section': {'type': 'string', 'enum': list(SECTIONS)},
                    'claim': {'type': 'string'},
                    'example': {'type': 'string'},
                },
                'required': ['section', 'claim', 'example'],
                'additionalProperties': False,
            },
        },
    },
    'required': ['claims'],
    'additionalProperties': False,
}


@dataclass(frozen=True)
class Claim:
    id: str
    section: str
    claim: str
    example: str = ''
    mark: str = ''

    @property
    def positive(self) -> bool:
        """Whether the claim says the voice does something (every section
        but `never`)."""
        return self.section != 'never'


def _json_reply(reply: str, what: str) -> dict:
    try:
        data = json.loads(reply)
    except ValueError as e:
        raise ProposalError(f'the {what} reply isn\'t JSON ({e})') from e
    if not isinstance(data, dict):
        raise ProposalError(f'the {what} reply isn\'t a JSON object')
    return data


def parse_claims(reply: str) -> tuple[list[Claim], list[str]]:
    """The claims in a reply, numbered `c01`.. in section order (the reply's
    order within a section), and the problems: a claim with no text is left
    out and named, a section with no claim is named. Raises ProposalError
    for a reply that isn't the schema's shape or holds no claim."""
    data = _json_reply(reply, 'description')
    items = data.get('claims')
    if not isinstance(items, list):
        raise ProposalError('the description reply has no `claims` list')
    problems, by_section = [], {s: [] for s in SECTIONS}
    for i, item in enumerate(items, start=1):
        if not isinstance(item, dict) or item.get('section') not in SECTIONS:
            problems.append(f'claim {i} has no known section; left out')
            continue
        text = ' '.join(str(item.get('claim', '')).split())
        if not text:
            problems.append(f'claim {i} ({item["section"]}) is empty; left out')
            continue
        by_section[item['section']].append(
            (text, ' '.join(str(item.get('example', '')).split())))
    claims = []
    for s in SECTIONS:
        if not by_section[s]:
            problems.append(f'no claim in section `{s}`')
        for text, example in by_section[s]:
            claims.append(Claim(f'c{len(claims) + 1:02d}', s, text, example))
    if not claims:
        raise ProposalError('the description reply holds no claim')
    return claims, problems


def description_prompt() -> str:
    return DESCRIPTION_PROMPT


# ============================================================================
# The exemplar shortlist (B4)
# ============================================================================

SHORTLIST_PROMPT = """\
Propose a shortlist of {ask} exemplar passages from the sample: the passages that show this voice at its most characteristic, for a writer (human or model) to study and imitate.

Each passage is a run of consecutive paragraphs within one of the sample's passages, {min} to {max} words in all (add up the word counts shown), that reads well on its own. Give its first and last paragraph numbers.

Tag each with its job, one of:
- description: a place, person, object or situation described
- argument: reasoning or persuasion, a case made by the narrator or a character
- turn: a moment where something changes (a realization, a reversal, a decision)
- humour: a passage whose point is comic
- quiet: a still, low-key or reflective moment
- dialogue: an exchange carried mostly by speech

Spread the shortlist across the jobs: every job the sample can supply, and no job more than a third of the list. Don't let two passages overlap. For each, say in one sentence what it shows about the voice."""

SHORTLIST_SCHEMA = {
    'type': 'object',
    'properties': {
        'passages': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'first': {'type': 'integer'},
                    'last': {'type': 'integer'},
                    'job': {'type': 'string', 'enum': list(JOBS)},
                    'why': {'type': 'string'},
                },
                'required': ['first', 'last', 'job', 'why'],
                'additionalProperties': False,
            },
        },
    },
    'required': ['passages'],
    'additionalProperties': False,
}


def shortlist_prompt() -> str:
    return SHORTLIST_PROMPT.format(ask=SHORTLIST_ASK, min=PASSAGE_MIN, max=PASSAGE_MAX)


@dataclass(frozen=True)
class Passage:
    """A shortlisted passage: `paragraphs` is its first and last paragraph
    within its piece ("412-415"), `text` its paragraphs as written, joined
    by blank lines. `distance`, `limit` and `typical` are from
    `PassageRange.judge` (None before)."""
    id: str
    job: str
    source: str
    paragraphs: str
    words: int
    text: str
    why: str = ''
    distance: float | None = None
    limit: float | None = None
    typical: bool | None = None
    pick: str = ''


def parse_shortlist(reply: str, sample: Sample) -> tuple[list[Passage], list[str]]:
    """The passages a reply names, cut from the sample, numbered `s01`..
    in the reply's order, and the refusals: a run outside the sample,
    backwards, across a passage break, overlapping an earlier passage, with
    an unknown job or outside `PASSAGE_MIN`..`PASSAGE_MAX` words, each
    named. Raises ProposalError for a reply that isn't the schema's shape."""
    data = _json_reply(reply, 'shortlist')
    items = data.get('passages')
    if not isinstance(items, list):
        raise ProposalError('the shortlist reply has no `passages` list')
    out, refused, used = [], [], set()
    for i, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            refused.append(f'passage {i}: not an object')
            continue
        first, last, job = item.get('first'), item.get('last'), item.get('job')
        where = f'passage {i} ([{first}]-[{last}], {job})'
        if not isinstance(first, int) or not isinstance(last, int):
            refused.append(f'{where}: no paragraph numbers')
            continue
        if job not in JOBS:
            refused.append(f'{where}: unknown job')
            continue
        a, b = sample.get(first), sample.get(last)
        if a is None or b is None:
            refused.append(f'{where}: outside the sample (1-{len(sample.paragraphs)})')
            continue
        if last < first:
            refused.append(f'{where}: ends before it starts')
            continue
        if a.window != b.window:
            refused.append(f'{where}: crosses from sample passage {a.window} to {b.window}')
            continue
        span = set(range(first, last + 1))
        if span & used:
            refused.append(f'{where}: overlaps an earlier passage')
            continue
        paras = sample.paragraphs[first - 1:last]
        words = sum(p.words for p in paras)
        if not PASSAGE_MIN <= words <= PASSAGE_MAX:
            refused.append(f'{where}: {words} words, not {PASSAGE_MIN}-{PASSAGE_MAX}')
            continue
        used |= span
        out.append(Passage(f's{len(out) + 1:02d}', job, a.source, f'{a.index}-{b.index}',
                           words, '\n\n'.join(p.text for p in paras),
                           ' '.join(str(item.get('why', '')).split())))
    return out, refused


# ============================================================================
# The typical range of a passage
# ============================================================================

#: passages are judged against the corpus's own passages of about their size:
#: a band runs from its value to the next (the last to `PASSAGE_MAX`)
PASSAGE_BANDS = (100, 150, 200, 300)
#: a passage is typical when its distance is at most this quantile of its
#: band's corpus passages
TYPICAL_QUANTILE = 0.9
#: corpus passages measured per band, at most (spaced evenly)
RANGE_WINDOWS = 400
#: a band with fewer corpus passages than this can't give a range
RANGE_MIN_WINDOWS = 20


def _passage_distance(fp: vp.Fingerprint, text: str, base: vp.Baseline) -> float:
    """A passage's distance from the fingerprint. Through `compare_values`
    on `measure(text)`: `compare` refuses a text under
    `voiceprint.MIN_COMPARE_WORDS`, which is the chunk scale's floor; the
    passage scale is handled here, by judging against passages."""
    return vp.compare_values(fp, vp.measure(text), base).distance


def _band_bounds(band: int) -> tuple[int, int]:
    i = PASSAGE_BANDS.index(band)
    upper = PASSAGE_BANDS[i + 1] - 1 if i + 1 < len(PASSAGE_BANDS) else PASSAGE_MAX
    return band, upper


def band_of(words: int) -> int:
    """The band a passage of `words` words is judged in (under the first
    band: the first)."""
    return max([b for b in PASSAGE_BANDS if b <= words] or [PASSAGE_BANDS[0]])


@dataclass(frozen=True)
class PassageRange:
    """Per band, the distance from the fingerprint at or under which a
    passage of that size is typical (`limits`: the corpus's own passages'
    `TYPICAL_QUANTILE`), and how many corpus passages each band had
    (`counts`, every band). A band with under `RANGE_MIN_WINDOWS` corpus
    passages has no limit (`thin`), and a passage in it can't be judged.
    Short passages vary more than the fingerprint's 2,000-word chunks, so a
    passage is judged against passages, not chunks."""
    fingerprint: vp.Fingerprint
    limits: dict[int, float]
    counts: dict[int, int]
    baseline: vp.Baseline = field(repr=False, default=None)

    @property
    def thin(self) -> tuple[int, ...]:
        """The bands with too few corpus passages for a limit."""
        return tuple(b for b in PASSAGE_BANDS if b not in self.limits)

    def thin_warning(self) -> str:
        """A WARNING line naming the thin bands ('' when there are none)."""
        if not self.thin:
            return ''
        bands = ', '.join(f'{lo}-{hi} words ({self.counts.get(b, 0)})'
                          for b in self.thin for lo, hi in [_band_bounds(b)])
        return (f'WARNING: the corpus has too few passages of {bands} for a typical '
                f'range (at least {RANGE_MIN_WINDOWS} each); a shortlisted passage of '
                f'that length can\'t be judged, so read it before picking it')

    def limit(self, words: int) -> float | None:
        """The limit for a passage of `words` words; None in a thin band."""
        return self.limits.get(band_of(words))

    def distance(self, text: str) -> float:
        return _passage_distance(self.fingerprint, text, self.baseline)

    def judge(self, passage: Passage) -> Passage:
        """`passage` with its distance, its band's limit and whether it's
        typical; unjudged (all three None) when its band is thin."""
        lim = self.limit(passage.words)
        if lim is None:
            return replace(passage, distance=None, limit=None, typical=None)
        d = self.distance(passage.text)
        return replace(passage, distance=round(d, 4), limit=round(lim, 4),
                       typical=d <= lim)


def _quantile(vals: Sequence[float], q: float) -> float:
    s = sorted(vals)
    pos = q * (len(s) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def passage_range(fp: vp.Fingerprint, texts: Mapping[str, str],
                  baseline: vp.Baseline | None = None) -> PassageRange:
    """The typical range of a passage of each band's size: runs of whole
    paragraphs of the corpus (`texts`, the fingerprinted pieces), each
    started at an evenly spaced paragraph and grown until it reaches the
    band, kept when it ends inside it; each run's distance from `fp`; the
    band's limit their `TYPICAL_QUANTILE`. Deterministic. A band with
    under `RANGE_MIN_WINDOWS` runs gets no limit (`PassageRange.thin`): a
    corpus of long paragraphs may have no run of 100-149 words, and a
    passage that short can hardly be cut from it either. Raises
    ProposalError when no band has enough runs."""
    base = baseline or vp.load_baseline()
    pieces = [(prose_paragraphs(t), [len(vp.words(p)) for p in prose_paragraphs(t)])
              for t in texts.values()]
    starts = [(k, i) for k, (paras, _) in enumerate(pieces) for i in range(len(paras))]
    limits, counts = {}, {}
    for band in PASSAGE_BANDS:
        lo, hi = _band_bounds(band)
        step = max(1, len(starts) // RANGE_WINDOWS)
        dists = []
        for k, i in starts[::step]:
            paras, lens = pieces[k]
            n, j = 0, i
            while j < len(paras) and n < lo:
                n += lens[j]
                j += 1
            if lo <= n <= hi:
                dists.append(_passage_distance(fp, '\n\n'.join(paras[i:j]), base))
        counts[band] = len(dists)
        if len(dists) >= RANGE_MIN_WINDOWS:
            limits[band] = _quantile(dists, TYPICAL_QUANTILE)
    if not limits:
        raise ProposalError(f'the corpus gives too few passages of any length for a typical '
                            f'range (at least {RANGE_MIN_WINDOWS} a band; '
                            + ', '.join(f'{b}: {n}' for b, n in counts.items()) + ')')
    return PassageRange(fp, limits, counts, base)


def auto_picks(passages: Sequence[Passage], least: int = SHORTLIST_MIN) -> list[str]:
    """The ids picked by the rule the reference voiceprint's exemplars were
    chosen by: every typical passage; if fewer than `least`, the rest
    nearest their limit (distance over limit) until `least`. In shortlist
    order. Every passage must have been judged: raises ProposalError
    naming those that aren't."""
    unjudged = [p.id for p in passages if p.typical is None]
    if unjudged:
        raise ProposalError(f'not judged: {", ".join(unjudged)}. Run `storyforge voice judge` '
                            f'first; a passage still unjudged after it is in a band too thin '
                            f'for a range, so pick by hand')
    picked = {p.id for p in passages if p.typical}
    rest = sorted((p for p in passages if not p.typical),
                  key=lambda p: (p.distance / p.limit, p.id))
    for p in rest[:max(0, least - len(picked))]:
        picked.add(p.id)
    return [p.id for p in passages if p.id in picked]


# ============================================================================
# Files
# ============================================================================

def _write_text(path: str, text: str) -> None:
    """Write `text` to `path` (UTF-8, LF) through a temporary file beside
    it, so an interrupted write never leaves a truncated file."""
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    tmp = f'{path}.tmp'
    try:
        with open(tmp, 'w', encoding='utf-8', newline='\n') as f:
            f.write(text)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def _write_rows(path: str, columns: Sequence[str], rows: Sequence[Mapping[str, str]]) -> None:
    """A pipe-delimited file, LF, no quoting; every cell through csv_safe."""
    lines = ['|'.join(columns)]
    lines += ['|'.join(csv_safe(str(r.get(c, ''))) for c in columns) for r in rows]
    _write_text(path, '\n'.join(lines) + '\n')


def _read_rows(path: str, columns: Sequence[str]) -> list[dict[str, str]]:
    """Rows of a file `_write_rows` wrote (an author may have edited it).
    Raises ProposalError for a missing file, another header, a row with the
    wrong number of cells, or a blank or repeated id."""
    try:
        raw = _read(path)
    except FileNotFoundError as e:
        raise ProposalError(f'{path} doesn\'t exist') from e
    except (OSError, UnicodeDecodeError) as e:
        raise ProposalError(f'{path} can\'t be read ({e})') from e
    lines = [ln for ln in raw.lstrip('﻿').replace('\r\n', '\n').split('\n') if ln.strip()]
    if not lines or lines[0].split('|') != list(columns):
        raise ProposalError(f'{path}: the header isn\'t {"|".join(columns)}')
    rows, seen = [], set()
    for n, line in enumerate(lines[1:], start=2):
        cells = line.split('|')
        if len(cells) != len(columns):
            raise ProposalError(f'{path} line {n}: {len(cells)} cells, not {len(columns)} '
                                f'(a `|` inside a cell splits it)')
        row = {c: v.strip() for c, v in zip(columns, cells)}
        if not row['id'] or row['id'] in seen:
            raise ProposalError(f'{path} line {n}: a blank or repeated id {row["id"]!r}')
        seen.add(row['id'])
        rows.append(row)
    return rows


def write_claims(voice_dir: str, claims: Sequence[Claim]) -> str:
    path = os.path.join(voice_dir, CLAIMS_FILE)
    _write_rows(path, CLAIM_COLUMNS, [c.__dict__ for c in claims])
    return path


def read_claims(voice_dir: str) -> list[Claim]:
    """The claims file as the author left it. Raises ProposalError (as
    `_read_rows`) or for an unknown section."""
    path = os.path.join(voice_dir, CLAIMS_FILE)
    out = []
    for r in _read_rows(path, CLAIM_COLUMNS):
        if r['section'] not in SECTIONS:
            raise ProposalError(f'{path}: claim {r["id"]} has section {r["section"]!r}, not '
                                f'one of {", ".join(SECTIONS)}')
        out.append(Claim(r['id'], r['section'], r['claim'], r['example'], r['mark']))
    return out


def _passage_row(p: Passage) -> dict[str, str]:
    return {'id': p.id, 'job': p.job, 'source': p.source, 'paragraphs': p.paragraphs,
            'words': str(p.words),
            'distance': '' if p.distance is None else f'{p.distance:.4f}',
            'limit': '' if p.limit is None else f'{p.limit:.4f}',
            'typical': '' if p.typical is None else ('yes' if p.typical else 'no'),
            'why': p.why, 'pick': p.pick}


def write_shortlist(voice_dir: str, passages: Sequence[Passage]) -> str:
    """`proposals/shortlist.csv` and a file per passage under
    `proposals/shortlist/`; passage files of an earlier shortlist that this
    one doesn't hold are removed (the shortlist is the model's, replaced
    whole)."""
    path = os.path.join(voice_dir, SHORTLIST_FILE)
    folder = os.path.join(voice_dir, SHORTLIST_DIR)
    os.makedirs(folder, exist_ok=True)
    keep = {f'{p.id}.md' for p in passages}
    for name in os.listdir(folder):
        if name.endswith('.md') and name not in keep:
            os.remove(os.path.join(folder, name))
    for p in passages:
        _write_text(os.path.join(folder, f'{p.id}.md'), p.text.strip() + '\n')
    _write_rows(path, SHORTLIST_COLUMNS, [_passage_row(p) for p in passages])
    return path


def _opt_float(s: str) -> float | None:
    return float(s) if s else None


def read_shortlist(voice_dir: str) -> list[Passage]:
    """The shortlist as the author left it, each passage's text read from
    its file (which the author may have trimmed; its words are counted
    again). Raises ProposalError (as `_read_rows`), or for an unknown job,
    a missing or unreadable passage file, or a figure that isn't a number."""
    path = os.path.join(voice_dir, SHORTLIST_FILE)
    out = []
    for r in _read_rows(path, SHORTLIST_COLUMNS):
        if r['job'] not in JOBS:
            raise ProposalError(f'{path}: {r["id"]} has job {r["job"]!r}, not one of '
                                f'{", ".join(JOBS)}')
        ppath = os.path.join(voice_dir, SHORTLIST_DIR, f'{r["id"]}.md')
        try:
            text = _read(ppath).strip()
        except (OSError, UnicodeDecodeError) as e:
            raise ProposalError(f'{r["id"]}\'s passage {ppath} can\'t be read ({e})') from e
        try:
            distance, limit = _opt_float(r['distance']), _opt_float(r['limit'])
        except ValueError as e:
            raise ProposalError(f'{path}: {r["id"]} has a distance or limit that isn\'t a '
                                f'number') from e
        typical = {'yes': True, 'no': False}.get(r['typical'])
        out.append(Passage(r['id'], r['job'], r['source'], r['paragraphs'],
                           len(vp.words(text)), text, r['why'], distance, limit,
                           typical, r['pick']))
    return out


def set_picks(voice_dir: str, ids: Sequence[str]) -> list[Passage]:
    """Write `yes` in `pick` for `ids` and clear it for the rest (the
    shortlist's passage files are left as they are). Returns the shortlist."""
    passages = [replace(p, pick='yes' if p.id in set(ids) else '')
                for p in read_shortlist(voice_dir)]
    _write_rows(os.path.join(voice_dir, SHORTLIST_FILE), SHORTLIST_COLUMNS,
                [_passage_row(p) for p in passages])
    return passages


def rejudge(voice_dir: str) -> tuple[PassageRange, list[Passage]]:
    """Measure the shortlist's passages against the current fingerprint and
    rewrite their `distance`, `limit` and `typical` (free; after the
    fingerprint changes, or after the author trims a passage). Picks and
    passage files are left as they are. Returns the range (its `thin`
    bands) and the passages."""
    voice = load_voice(voice_dir)
    rng = passage_range(voice.fingerprint, voice.texts)
    passages = [rng.judge(p) for p in read_shortlist(voice_dir)]
    _write_rows(os.path.join(voice_dir, SHORTLIST_FILE), SHORTLIST_COLUMNS,
                [_passage_row(p) for p in passages])
    return rng, passages


# ============================================================================
# Accepting
# ============================================================================

def render_description(claims: Sequence[Claim], author: str = '') -> str:
    """description.md from the claims marked yes, by section."""
    kept = [c for c in claims if c.mark.lower() == 'yes']
    title = f'# The described voice: {author}' if author else '# The described voice'
    lines = [title, '',
             f'Written by `storyforge voice accept` from {CLAIMS_FILE}: the claims the '
             f'author marked yes ({len(kept)} of {len(claims)}). To change it, edit and '
             f'mark the claims there and accept again.']
    for s in SECTIONS:
        items = [c for c in kept if c.section == s]
        if items:
            lines += ['', f'## {SECTION_HEADINGS[s]}', '']
            lines += [f'- {c.claim}' for c in items]
    return '\n'.join(lines) + '\n'


@dataclass(frozen=True)
class Accepted:
    """What `accept_description` / `accept_exemplars` wrote, and notes (each
    a line the CLI prints: a WARNING or a NOTE)."""
    path: str
    kept: int
    total: int
    notes: tuple[str, ...] = ()


def accept_description(voice_dir: str) -> Accepted:
    """Write description.md from the marked claims. Raises ProposalError,
    nothing written, when a claim is unmarked or marked anything but yes or
    no, or when no claim is marked yes."""
    claims = read_claims(voice_dir)
    unmarked = [c.id for c in claims if not c.mark]
    bad = [f'{c.id} ({c.mark!r})' for c in claims if c.mark and c.mark.lower() not in MARKS]
    if unmarked or bad:
        parts = []
        if unmarked:
            parts.append(f'unmarked: {", ".join(unmarked)}')
        if bad:
            parts.append(f'marked neither yes nor no: {", ".join(bad)}')
        raise ProposalError(f'{CLAIMS_FILE}: mark every claim yes or no ({"; ".join(parts)}). '
                            f'Nothing written.')
    kept = [c for c in claims if c.mark.lower() == 'yes']
    if not kept:
        raise ProposalError(f'{CLAIMS_FILE}: no claim is marked yes, so there is no '
                            f'description to write. Nothing written.')
    path = os.path.join(voice_dir, DESCRIPTION_FILE)
    _write_text(path, render_description(claims, _author(voice_dir)))
    return Accepted(path, len(kept), len(claims))


def accept_exemplars(voice_dir: str, picks: Sequence[str] | None = None) -> Accepted:
    """Copy the picked passages to exemplars/ and update their index.

    `picks`, when given, are the ids to pick in place of the `pick` column;
    the column is rewritten to them only once the exemplars are written.
    Raises ProposalError, nothing written, when a pick isn't yes, no or
    blank, `picks` names a passage the shortlist doesn't hold, no passage is
    picked, a picked passage (perhaps trimmed by the author) is outside
    `PASSAGE_MIN`..`PASSAGE_MAX` words, or a picked passage's file in
    exemplars/ exists without an index row (someone else's file).

    Accept owns only the shortlist's passages: a shortlisted passage that's
    picked is written (replacing its earlier copy), and one that isn't
    picked is taken out of the bank if an earlier accept put it there. Every
    other index row (an earlier shortlist's picks, or an exemplar the author
    added) is kept as it is. Files in exemplars/ the index doesn't name are
    left alone and noted. A bank of fewer than `SHORTLIST_MIN` or more than
    `SHORTLIST_MAX` exemplars is a WARNING note: the plan's bank is 20 to 40
    passages."""
    passages = read_shortlist(voice_dir)
    if picks is not None:
        unknown = sorted(set(picks) - {p.id for p in passages})
        if unknown:
            raise ProposalError(f'{SHORTLIST_FILE} holds no passage {", ".join(unknown)}. '
                                f'Nothing written.')
        passages = [replace(p, pick='yes' if p.id in set(picks) else '') for p in passages]
    bad = [f'{p.id} ({p.pick!r})' for p in passages if p.pick.lower() not in ('', *MARKS)]
    if bad:
        raise ProposalError(f'{SHORTLIST_FILE}: `pick` is yes, no or blank, not '
                            f'{", ".join(bad)}. Nothing written.')
    picked = [p for p in passages if p.pick.lower() == 'yes']
    if not picked:
        raise ProposalError(f'{SHORTLIST_FILE}: no passage has `pick` yes. Nothing written.')
    wrong = [f'{p.id} ({p.words} words)' for p in picked
             if not PASSAGE_MIN <= p.words <= PASSAGE_MAX]
    if wrong:
        raise ProposalError(f'picked passages outside {PASSAGE_MIN}-{PASSAGE_MAX} words: '
                            f'{", ".join(wrong)}. Nothing written.')
    folder = os.path.join(voice_dir, EXEMPLARS_DIR)
    index = os.path.join(voice_dir, EXEMPLARS_INDEX)
    old = _read_rows(index, EXEMPLAR_COLUMNS) if os.path.isfile(index) else []
    old_ids = {r['id'] for r in old}
    clash = [p.id for p in picked if p.id not in old_ids
             and os.path.exists(os.path.join(folder, f'{p.id}.md'))]
    if clash:
        raise ProposalError(f'{EXEMPLARS_DIR}/ already holds '
                            f'{", ".join(c + ".md" for c in clash)}, which its index doesn\'t '
                            f'name; move it or add it to {EXEMPLARS_INDEX}. Nothing written.')
    shortlisted = {p.id for p in passages}
    keep = {p.id for p in picked}
    carried = [r for r in old if r['id'] not in shortlisted]
    os.makedirs(folder, exist_ok=True)
    for r in old:
        f = os.path.join(folder, f'{r["id"]}.md')
        if r['id'] in shortlisted and r['id'] not in keep and os.path.isfile(f):
            os.remove(f)
    for p in picked:
        _write_text(os.path.join(folder, f'{p.id}.md'), p.text.strip() + '\n')
    rows = carried + [{'id': p.id, 'job': p.job, 'source': p.source,
                       'paragraphs': p.paragraphs, 'words': str(p.words), 'why': p.why}
                      for p in picked]
    _write_rows(index, EXEMPLAR_COLUMNS, rows)
    if picks is not None:
        _write_rows(os.path.join(voice_dir, SHORTLIST_FILE), SHORTLIST_COLUMNS,
                    [_passage_row(p) for p in passages])
    notes = []
    named = {r['id'] for r in rows}
    unlisted = sorted(n for n in os.listdir(folder)
                      if n.endswith('.md') and n[:-3] not in named)
    if unlisted:
        notes.append(f'NOTE: {EXEMPLARS_DIR}/ also holds {", ".join(unlisted)}, which its '
                     f'index doesn\'t name; left as they are')
    if carried:
        notes.append(f'NOTE: kept {len(carried)} exemplar(s) the shortlist doesn\'t hold '
                     f'({", ".join(r["id"] for r in carried)})')
    if not SHORTLIST_MIN <= len(rows) <= SHORTLIST_MAX:
        notes.append(f'WARNING: the bank holds {len(rows)} exemplars; it is meant to be '
                     f'{SHORTLIST_MIN} to {SHORTLIST_MAX}')
    jobs = {r['job'] for r in rows}
    missing = [j for j in JOBS if j not in jobs]
    if missing:
        notes.append(f'NOTE: no exemplar for the job(s) {", ".join(missing)}')
    return Accepted(index, len(picked), len(passages), tuple(notes))


# ============================================================================
# The calls
# ============================================================================

#: tokens per character of the prompt (the numbered sample and the
#: fingerprint's figures): 66,804 tokens for 196,868 characters on Austen
_TOKENS_PER_CHAR = 0.34
#: output tokens per call, thinking included, for the forecast (Austen,
#: 2026-11-08: 1,356 and 5,475)
FORECAST_OUTPUT = {'description': 1500, 'shortlist': 5500}


def forecast(system: Sequence[dict], model: str, calls: Sequence[str] = ('description',
                                                                          'shortlist')) -> float:
    """What `calls` would cost, in US dollars: each sends the whole system
    block and its own prompt, and writes about `FORECAST_OUTPUT` tokens (a
    forecast, not a bound: thinking varies)."""
    from storyforge.costs import calculate_cost
    sys_chars = sum(len(b['text']) for b in system)
    total = 0.0
    for call in calls:
        prompt = description_prompt() if call == 'description' else shortlist_prompt()
        total += calculate_cost(model, int((sys_chars + len(prompt)) * _TOKENS_PER_CHAR),
                                FORECAST_OUTPUT[call])
    return total


def _save_reply(reply_file: str | None, response: dict) -> None:
    if reply_file:
        os.makedirs(os.path.dirname(reply_file), exist_ok=True)
        with open(reply_file, 'w', encoding='utf-8') as f:
            json.dump(response, f, indent=1)


def _call(system: list[dict], prompt: str, schema: dict, model: str, tokens: int,
          label: str, reply_file: str | None) -> str:
    from storyforge import api
    try:
        response = api.invoke(prompt, model, max_tokens=tokens, label=label, system=system,
                              output_schema=schema)
    except api.RefusalError as e:
        _save_reply(reply_file, e.response)     # a refusal is paid for too
        raise
    _save_reply(reply_file, response)
    problem = api.stop_problem(response)
    if problem:
        raise ProposalError(f'the {label} reply is unusable: {problem}')
    return api.extract_text(response)


def propose_description(system: list[dict], model: str,
                        reply_file: str | None = None) -> tuple[list[Claim], list[str]]:
    """One call: the claims and the problems (`parse_claims`). The raw reply
    is written to `reply_file` first. Raises ProposalError for an unusable
    reply, `api.RefusalError` for a refusal."""
    reply = _call(system, description_prompt(), CLAIMS_SCHEMA, model, DESCRIPTION_TOKENS,
                  'voice description', reply_file)
    return parse_claims(reply)


def propose_shortlist(system: list[dict], sample: Sample, model: str,
                      reply_file: str | None = None) -> tuple[list[Passage], list[str]]:
    """One call: the passages and the refusals (`parse_shortlist`), not yet
    judged against the fingerprint."""
    reply = _call(system, shortlist_prompt(), SHORTLIST_SCHEMA, model, SHORTLIST_TOKENS,
                  'exemplar shortlist', reply_file)
    return parse_shortlist(reply, sample)
