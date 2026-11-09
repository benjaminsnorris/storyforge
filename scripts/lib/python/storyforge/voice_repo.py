"""The author voice repo and the book's `voice:` block (#652, plan B0).

A voiceprint belongs to an author, not a book. Each author makes it once, in
their own repo, and every book points to it, the way `series.canon` points at
a shared canon: read in place, never copied into the book.

The repo (`storyforge voice init` makes it; nothing in it is a book):

    <author-voice>/
      voice.yaml          # the author's name and which pieces count
      corpus/             # the author's writing, as imported (`voice import`)
        index.csv         # one row per piece: file|title|date|kind|source|use
      fingerprint.json    # `voice fingerprint` (storyforge.voiceprint)
      description.md      # `voice propose` / `voice accept` (voiceprint_proposals)
      exemplars/          # likewise: exemplars.csv and one <id>.md per passage
      fiction/            # fiction anchors, one folder per narrator stance (#654)

`voice.yaml`:

    author: Ben Norris
    kinds:              # the kinds of piece that count (KINDS)
      - essay
      - fiction
    min_words: 500      # a piece with less prose than this doesn't count

`corpus/index.csv` (pipe-delimited, LF, no quoting): `file` is the piece's
path in the repo (`corpus/2019-03-02-on-walking.md`, the name the fingerprint
gives it), `date` is `YYYY-MM-DD`, `YYYY-MM`, `YYYY` or blank (unknown),
`kind` one of KINDS, `source` where it came from, and `use` the author's
override: blank (voice.yaml's rules decide), `in`, `out` or `held-out`
(kept out of the fingerprint to test it on, as the Austen reference holds out
*Emma*). `counted_pieces` applies the rules; the fingerprint is made from
exactly those pieces, in index order.

A book names the repo in its `storyforge.yaml`:

    voice:
      author: ../ben-voice          # the author voice repo, relative to the book
      narrator: fiction/close-third # optional: the fiction anchor, in the repo

`book_voice` loads it: the description, the exemplar bank, the fiction anchor
and the fingerprint's path, plus the book's own `reference/voice/book.md`
when it has one. `author_voice_section` renders it for the drafting prompt; a
book without the block gets '' and its prompt is exactly what it was. A block
that can't be used (a key it doesn't take, a repo that isn't there or isn't
a voice repo, no description or exemplars yet, a narrator folder with no
`.md` file) raises `VoiceError`, a `source.SourceError`, so the dispatcher
turns it into `ERROR: ...` and exit 1; `write` calls `require_voice` up
front, before a branch or spend.

The corpus is read here and by the voiceprint's own calls (`voice propose`),
and sent nowhere else: the drafting prompt carries the description and the
exemplars the author chose, never the corpus.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

from storyforge.common import parse_yaml_scalar
from storyforge.source import SourceError

VOICE_FILE = 'voice.yaml'
CORPUS_DIR = 'corpus'
INDEX_FILE = os.path.join(CORPUS_DIR, 'index.csv')
INDEX_COLUMNS = ('file', 'title', 'date', 'kind', 'source', 'use')
FINGERPRINT_FILE = 'fingerprint.json'
DESCRIPTION_FILE = 'description.md'
EXEMPLARS_DIR = 'exemplars'
FICTION_DIR = 'fiction'
#: the folders `voice init` makes (a `.gitkeep` in each empty one)
LAYOUT_DIRS = (CORPUS_DIR, EXEMPLARS_DIR, FICTION_DIR)

#: the kinds of piece (plan B1). A link post is mostly someone else's words
#: and a note is short, so they carry less voice and are out by default
KINDS = ('essay', 'fiction', 'notes', 'link')
DEFAULT_KINDS = ('essay', 'fiction')
#: a piece with fewer words of prose than this doesn't count by default
DEFAULT_MIN_WORDS = 500
#: the `use` column's values ('' = voice.yaml's rules decide)
USES = ('', 'in', 'out', 'held-out')
#: the keys voice.yaml takes
SETTINGS_KEYS = ('author', 'kinds', 'min_words')

#: the keys the book's `voice:` block takes
BLOCK_KEYS = ('author', 'narrator')
#: the book's own voice notes, read beside the author's voice
BOOK_NOTES = os.path.join('reference', 'voice', 'book.md')
#: scalar values that mean "nothing" in YAML: never a path
_NOT_A_PATH = ('~', 'null', 'none', 'nil')


class VoiceRepoError(Exception):
    """An author voice repo (voice.yaml, corpus/index.csv, a piece) that
    can't be used; the message says why."""


class VoiceError(SourceError):
    """A book's `voice:` block, or the voice repo it names, that can't be
    used."""


def _read(path: str) -> str:
    with open(path, encoding='utf-8-sig') as f:
        return f.read()


# ============================================================================
# voice.yaml
# ============================================================================

@dataclass(frozen=True)
class Settings:
    """voice.yaml: the author's name ('' when it has none), the kinds that
    count, and the least words of prose a counted piece has."""
    author: str = ''
    kinds: tuple[str, ...] = DEFAULT_KINDS
    min_words: int = DEFAULT_MIN_WORDS


def render_settings(settings: Settings) -> str:
    """voice.yaml's text, as `voice init` writes it."""
    kinds = ''.join(f'  - {k}\n' for k in settings.kinds)
    author = settings.author.replace('"', "'")
    return (
        '# The author voice repo (`storyforge voice init`). A book points here with\n'
        '#   voice:\n'
        '#     author: <path to this repo, relative to the book>\n'
        '# and Storyforge reads it in place, never copying it into the book.\n'
        f'author: "{author}"\n'
        f'# The kinds of piece that count toward the voiceprint ({", ".join(KINDS)}).\n'
        '# Notes and link posts carry less voice, so they are out by default.\n'
        f'kinds:\n{kinds}'
        '# A piece with fewer words of prose than this does not count. In\n'
        "# corpus/index.csv, a piece's `use` column overrides both rules: in, out\n"
        '# or held-out (kept out of the fingerprint, to test it on).\n'
        f'min_words: {settings.min_words}\n')


def read_settings(voice_dir: str) -> Settings:
    """voice.yaml's settings. Raises VoiceRepoError when it's missing or
    can't be read, has a key it doesn't take (the provisional `corpus:`
    list among them: the corpus is listed in corpus/index.csv), gives one
    twice, or a kind or min_words that can't be used."""
    path = os.path.join(voice_dir, VOICE_FILE)
    try:
        lines = _read(path).splitlines()
    except FileNotFoundError as e:
        raise VoiceRepoError(f'{voice_dir} has no {VOICE_FILE}: run this in the author voice '
                             f'repo, or make one with `storyforge voice init`') from e
    except (OSError, UnicodeDecodeError) as e:
        raise VoiceRepoError(f'{path} can\'t be read ({e})') from e
    found: dict[str, object] = {}
    current = None
    for n, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            continue
        if not line[0].isspace():
            m = re.match(r'^([A-Za-z_]\w*):\s*(.*)$', line)
            if not m:
                raise VoiceRepoError(f'{path} line {n}: can\'t read {stripped!r} '
                                     f'(write `key: value`)')
            key, raw = m.group(1), m.group(2)
            if key == 'corpus':
                raise VoiceRepoError(f'{path} line {n}: voice.yaml lists no corpus; each '
                                     f'piece is a row of {INDEX_FILE} (see '
                                     f'references/voiceprints/README.md)')
            if key not in SETTINGS_KEYS:
                raise VoiceRepoError(f'{path} line {n}: `{key}` isn\'t a voice.yaml key '
                                     f'({", ".join(SETTINGS_KEYS)})')
            if key in found:
                raise VoiceRepoError(f'{path}: `{key}` is given twice')
            current = key
            value = '' if raw.strip().startswith('#') else raw
            if key == 'kinds':
                if value.strip():
                    raise VoiceRepoError(f'{path} line {n}: write the kinds as a list, '
                                         f'one `- kind` a line')
                found[key] = []
            else:
                found[key] = parse_yaml_scalar(value)
            continue
        if current == 'kinds' and stripped.startswith('-'):
            kind = parse_yaml_scalar(stripped[1:])
            if kind not in KINDS:
                raise VoiceRepoError(f'{path} line {n}: kind {kind!r} isn\'t one of '
                                     f'{", ".join(KINDS)}')
            found['kinds'].append(kind)     # type: ignore[union-attr]
            continue
        raise VoiceRepoError(f'{path} line {n}: can\'t read {stripped!r}')
    min_words = DEFAULT_MIN_WORDS
    if 'min_words' in found:
        try:
            min_words = int(str(found['min_words']))
        except ValueError as e:
            raise VoiceRepoError(f'{path}: min_words {found["min_words"]!r} isn\'t a '
                                 f'whole number') from e
        if min_words < 0:
            raise VoiceRepoError(f'{path}: min_words can\'t be negative')
    kinds = tuple(found['kinds']) if 'kinds' in found else DEFAULT_KINDS  # type: ignore
    if not kinds:
        raise VoiceRepoError(f'{path}: `kinds` lists no kind, so no piece would count')
    return Settings(str(found.get('author', '')), kinds, min_words)


# ============================================================================
# The repo and its corpus
# ============================================================================

def book_above(path: str) -> str | None:
    """The book `path` is in (the nearest directory at or above it with a
    storyforge.yaml), or None."""
    from storyforge.common import find_project_root
    return find_project_root(path)


def check_repo(voice_dir: str) -> None:
    """Raise VoiceRepoError unless `voice_dir` is an author voice repo: it
    has voice.yaml and isn't in a book."""
    book = book_above(voice_dir)
    if book:
        where = ('is a book (it has storyforge.yaml)'
                 if os.path.realpath(book) == os.path.realpath(voice_dir)
                 else f'is in a book ({book} has storyforge.yaml)')
        raise VoiceRepoError(f'{voice_dir} {where}; run this in the author voice repo, '
                             f'which lives outside the book')
    if not os.path.isfile(os.path.join(voice_dir, VOICE_FILE)):
        raise VoiceRepoError(f'{voice_dir} has no {VOICE_FILE}: run this in the author voice '
                             f'repo, or make one with `storyforge voice init`')


def init_repo(voice_dir: str, author: str = '') -> list[str]:
    """Make the voice repo's layout in `voice_dir` (made if missing):
    voice.yaml with the default settings, corpus/index.csv's header, and
    exemplars/ and fiction/ (fingerprint.json and description.md are
    written later, by `voice fingerprint` and `voice accept`). Returns the
    paths made, relative to the repo. Raises VoiceRepoError inside a book,
    or when voice.yaml or the index is already there (nothing is
    replaced)."""
    from storyforge.voiceprint_proposals import _write_text
    voice_dir = os.path.abspath(voice_dir)
    book = book_above(voice_dir)
    if book:
        raise VoiceRepoError(f'{voice_dir} is in a book ({book} has storyforge.yaml); make the '
                             f'voice repo outside it (say ../{os.path.basename(book)}-voice) '
                             f'and point the book at it with a `voice:` block')
    for rel in (VOICE_FILE, INDEX_FILE):
        if os.path.exists(os.path.join(voice_dir, rel)):
            raise VoiceRepoError(f'{os.path.join(voice_dir, rel)} is already there; '
                                 f'`voice init` replaces nothing')
    made = []
    _write_text(os.path.join(voice_dir, VOICE_FILE), render_settings(Settings(author)))
    made.append(VOICE_FILE)
    _write_text(os.path.join(voice_dir, INDEX_FILE), '|'.join(INDEX_COLUMNS) + '\n')
    made.append(INDEX_FILE)
    for d in (EXEMPLARS_DIR, FICTION_DIR):
        folder = os.path.join(voice_dir, d)
        os.makedirs(folder, exist_ok=True)
        if not os.listdir(folder):
            _write_text(os.path.join(folder, '.gitkeep'), '')
            made.append(f'{d}/')
    return made


@dataclass(frozen=True)
class IndexRow:
    """One piece of corpus/index.csv."""
    file: str
    title: str = ''
    date: str = ''
    kind: str = 'essay'
    source: str = ''
    use: str = ''

    def cells(self) -> dict[str, str]:
        return {c: getattr(self, c) for c in INDEX_COLUMNS}


_DATE_RE = re.compile(r'^\d{4}(?:-\d{2}(?:-\d{2})?)?$')


def read_index(voice_dir: str) -> list[IndexRow]:
    """corpus/index.csv's rows, in order. Raises VoiceRepoError for a
    missing or unreadable file, another header, a row with the wrong number
    of cells, a blank or repeated file, a file outside corpus/, or a date,
    kind or use that isn't one the index takes."""
    path = os.path.join(voice_dir, INDEX_FILE)
    try:
        raw = _read(path)
    except FileNotFoundError as e:
        raise VoiceRepoError(f'{path} doesn\'t exist: `storyforge voice init` makes it, and '
                             f'`voice import` fills it') from e
    except (OSError, UnicodeDecodeError) as e:
        raise VoiceRepoError(f'{path} can\'t be read ({e})') from e
    lines = [ln for ln in raw.replace('\r\n', '\n').split('\n') if ln.strip()]
    if not lines or lines[0].split('|') != list(INDEX_COLUMNS):
        raise VoiceRepoError(f'{path}: the header isn\'t {"|".join(INDEX_COLUMNS)}')
    rows, seen = [], set()
    for n, line in enumerate(lines[1:], start=2):
        cells = [c.strip() for c in line.split('|')]
        if len(cells) != len(INDEX_COLUMNS):
            raise VoiceRepoError(f'{path} line {n}: {len(cells)} cells, not '
                                 f'{len(INDEX_COLUMNS)} (a `|` inside a cell splits it)')
        row = IndexRow(*cells)
        where = f'{path} line {n}'
        norm = os.path.normpath(row.file) if row.file else ''
        if not norm or norm in seen:
            raise VoiceRepoError(f'{where}: a blank or repeated file {row.file!r}')
        if not norm.startswith(CORPUS_DIR + os.sep) or os.path.isabs(row.file):
            raise VoiceRepoError(f'{where}: {row.file!r} isn\'t in {CORPUS_DIR}/')
        if row.date and not _DATE_RE.match(row.date):
            raise VoiceRepoError(f'{where}: date {row.date!r} isn\'t YYYY-MM-DD, YYYY-MM, '
                                 f'YYYY or blank')
        if row.kind not in KINDS:
            raise VoiceRepoError(f'{where}: kind {row.kind!r} isn\'t one of {", ".join(KINDS)}')
        if row.use not in USES:
            raise VoiceRepoError(f'{where}: use {row.use!r} isn\'t blank, in, out or held-out')
        seen.add(norm)
        rows.append(row)
    return rows


def write_index(voice_dir: str, rows: list[IndexRow]) -> str:
    """Write corpus/index.csv (LF, every cell through csv_safe). Returns its
    path."""
    from storyforge.voiceprint_proposals import _write_rows
    path = os.path.join(voice_dir, INDEX_FILE)
    _write_rows(path, INDEX_COLUMNS, [r.cells() for r in rows])
    return path


def prose_words(text: str) -> int:
    """Words of prose in `text`, as the fingerprint counts them (headings,
    scene breaks and captions left out)."""
    from storyforge import voiceprint as vp
    return sum(len(vp.words(p)) for p in vp.paragraphs(text))


@dataclass(frozen=True)
class CorpusPiece:
    """A piece of the corpus with its words of prose and whether it counts
    (and, when it doesn't, why)."""
    row: IndexRow
    words: int
    counts: bool
    why: str


def judge_piece(row: IndexRow, words: int, settings: Settings) -> tuple[bool, str]:
    """Whether a piece counts toward the fingerprint, and why not."""
    if row.use == 'in':
        return True, ''
    if row.use == 'out':
        return False, 'out (the index says so)'
    if row.use == 'held-out':
        return False, 'held out'
    if row.kind not in settings.kinds:
        return False, f'a {row.kind} piece (voice.yaml counts {", ".join(settings.kinds)})'
    if words < settings.min_words:
        return False, f'{words} words (voice.yaml\'s min_words is {settings.min_words})'
    return True, ''


def corpus(voice_dir: str) -> tuple[list[CorpusPiece], dict[str, str]]:
    """Every piece of the index with its words and whether it counts, and
    the text of each by file. Raises VoiceRepoError as `read_settings` and
    `read_index`, or for a piece whose file is missing or can't be read."""
    settings = read_settings(voice_dir)
    pieces, texts = [], {}
    for row in read_index(voice_dir):
        path = os.path.join(voice_dir, row.file)
        try:
            text = _read(path)
        except FileNotFoundError as e:
            raise VoiceRepoError(f'{INDEX_FILE} names {row.file}, which isn\'t there') from e
        except (OSError, UnicodeDecodeError) as e:
            raise VoiceRepoError(f'{row.file} can\'t be read ({e})') from e
        words = prose_words(text)
        counts, why = judge_piece(row, words, settings)
        pieces.append(CorpusPiece(row, words, counts, why))
        texts[row.file] = text
    return pieces, texts


def counted_pieces(voice_dir: str) -> dict[str, str]:
    """The pieces that count, by file in index order: what the fingerprint
    is made from."""
    pieces, texts = corpus(voice_dir)
    return {p.row.file: texts[p.row.file] for p in pieces if p.counts}


def corpus_summary(pieces: list[CorpusPiece]) -> list[str]:
    """Lines saying what the corpus holds and what counts; a WARNING line
    when what counts is under `voiceprint.MIN_CORPUS_WORDS`."""
    from storyforge.voiceprint import MIN_CORPUS_WORDS
    counted = [p for p in pieces if p.counts]
    words = sum(p.words for p in counted)
    lines = [f'Corpus: {len(pieces)} piece(s), {sum(p.words for p in pieces):,} words; '
             f'{len(counted)} count toward the fingerprint, {words:,} words']
    reasons: dict[str, int] = {}
    for p in pieces:
        if not p.counts:
            key = re.sub(r'^\d+ words', 'too short', p.why)
            reasons[key] = reasons.get(key, 0) + 1
    for why, n in sorted(reasons.items(), key=lambda kv: (-kv[1], kv[0])):
        lines.append(f'  not counted: {n} {why}')
    if words < MIN_CORPUS_WORDS:
        lines.append(f'WARNING: the pieces that count hold {words:,} words; a stable '
                     f'fingerprint needs at least {MIN_CORPUS_WORDS:,} '
                     f'(voiceprint.MIN_CORPUS_WORDS). Import more, or let more kinds '
                     f'count in {VOICE_FILE}.')
    return lines


# ============================================================================
# The book's `voice:` block
# ============================================================================

@dataclass(frozen=True)
class VoiceRef:
    """A book's `voice:` block: the author repo and narrator as written,
    and the repo's absolute path."""
    author: str
    narrator: str
    author_dir: str


def _block_lines(project_dir: str) -> list[str] | None:
    """The `voice:` block's child lines, or None without one."""
    from storyforge.common import StoryforgeYamlError, _read_yaml_lines, _top_level_block_span
    yaml_file = os.path.join(project_dir, 'storyforge.yaml')
    if not os.path.isfile(yaml_file):
        return None
    try:
        lines = _read_yaml_lines(yaml_file)
    except (OSError, StoryforgeYamlError) as e:
        raise VoiceError(f'storyforge.yaml could not be read: {e}') from e
    for line in lines:
        if re.match(r'^\s+voice:\s*(#.*)?\r?\n?$', line):
            raise VoiceError('storyforge.yaml: `voice:` is indented under another block; it '
                             'is a top-level block of its own (not under `project:`)')
    if sum(1 for line in lines if re.match(r'^voice:', line)) > 1:
        raise VoiceError('storyforge.yaml: `voice:` is given twice; keep one block')
    try:
        span = _top_level_block_span(lines, 'voice')
    except StoryforgeYamlError as e:
        raise VoiceError(f'{e} (the `voice:` block takes author and narrator)') from e
    if span is None:
        return None
    return [ln.rstrip('\r\n') for ln in lines[span.first_child:span.end]]


def voice_ref(project_dir: str) -> VoiceRef | None:
    """The book's `voice:` block, or None without one. Its own keys are read
    at its indentation (as `source._direct_keys` reads `source:`), so a key
    nested deeper is never taken for one of them.

    Raises:
        VoiceError: the block is indented, given twice, or a one-line value;
            it has a key it doesn't take, gives one twice, has a line that
            isn't `key: value`, or names no author; the author isn't a path
            or isn't a directory.
    """
    block = _block_lines(project_dir)
    if block is None:
        return None
    content = [ln for ln in block if ln.strip() and not ln.lstrip().startswith('#')]
    keys: dict[str, str] = {}
    indent = len(content[0]) - len(content[0].lstrip()) if content else 0
    for line in content:
        stripped = line.strip()
        m = re.match(r'^(\w+):\s*(.*)$', stripped)
        if len(line) - len(line.lstrip()) != indent or not m:
            raise VoiceError(f'storyforge.yaml: can\'t read {stripped!r} in the `voice:` block '
                             f'(write `author: <path>` and, if you like, `narrator: <path>`)')
        key, raw = m.group(1), m.group(2)
        if key not in BLOCK_KEYS:
            raise VoiceError(f'storyforge.yaml: the `voice:` block has `{key}`; it takes '
                             f'{", ".join(BLOCK_KEYS)}')
        if key in keys:
            raise VoiceError(f'storyforge.yaml: the `voice:` block gives `{key}` twice')
        value = parse_yaml_scalar(raw)
        if value.lower() in _NOT_A_PATH or raw.strip().startswith(('[', '{')):
            raise VoiceError(f'voice.{key}: {raw.strip()!r} is not a path')
        keys[key] = value
    author = keys.get('author', '')
    if not author:
        raise VoiceError('storyforge.yaml: the `voice:` block names no author repo; write '
                         '`author: ../<your-voice-repo>`, or remove the block')
    author_dir = os.path.normpath(os.path.join(project_dir, os.path.expanduser(author)))
    if not os.path.isdir(author_dir):
        raise VoiceError(f'voice.author: {author} is not there ({author_dir})')
    return VoiceRef(author, keys.get('narrator', ''), author_dir)


@dataclass(frozen=True)
class BookVoice:
    """The voice a book is written in: the author repo's name, description
    (provenance comments left out), exemplar bank, fiction anchor (each
    file as (path in the repo, text); empty without `narrator`), the
    fingerprint's path (which may not exist yet: `score --voice` says so),
    and the book's own `reference/voice/book.md` ('' without one)."""
    ref: VoiceRef
    author: str
    description: str
    exemplars: object   # voiceprint_proposals.ExemplarBank
    anchor: tuple[tuple[str, str], ...]
    fingerprint_path: str
    book_notes: str


def _anchor(ref: VoiceRef) -> tuple[tuple[str, str], ...]:
    if not ref.narrator:
        return ()
    root = os.path.realpath(ref.author_dir)
    full = os.path.realpath(os.path.join(root, ref.narrator))
    if full != root and not full.startswith(root + os.sep):
        raise VoiceError(f'voice.narrator: {ref.narrator} is outside the author voice repo; '
                         f'name a folder in it (fiction/<stance>)')
    if os.path.isdir(full):
        names = sorted(n for n in os.listdir(full) if n.lower().endswith('.md')
                       and os.path.isfile(os.path.join(full, n)))
        if not names:
            raise VoiceError(f'voice.narrator: {ref.narrator} holds no .md file')
        files = [os.path.join(full, n) for n in names]
    elif os.path.isfile(full):
        files = [full]
    else:
        raise VoiceError(f'voice.narrator: {ref.narrator} is not in the author voice repo '
                         f'({full})')
    out = []
    for path in files:
        rel = os.path.relpath(path, root)
        try:
            text = _read(path).strip()
        except (OSError, UnicodeDecodeError) as e:
            raise VoiceError(f'voice.narrator: {rel} can\'t be read ({e})') from e
        if not text:
            raise VoiceError(f'voice.narrator: {rel} is empty')
        out.append((rel, text))
    return tuple(out)


def book_voice(project_dir: str) -> BookVoice | None:
    """The book's voice, or None without a `voice:` block.

    Raises:
        VoiceError: as `voice_ref`; the author dir isn't a voice repo (no
            voice.yaml, or it's a book); description.md or the exemplar
            bank is missing, can't be read or is empty (they're the voice
            the drafting prompt carries: `voice propose` and `voice accept`
            make them); the narrator is outside the repo, missing, empty
            or unreadable; reference/voice/book.md can't be read.
    """
    from storyforge import voiceprint_proposals as vpp
    ref = voice_ref(project_dir)
    if ref is None:
        return None
    where = f'voice.author ({ref.author})'
    try:
        vpp.check_voice_dir(ref.author_dir)
        settings = read_settings(ref.author_dir)
    except (vpp.ProposalError, VoiceRepoError) as e:
        raise VoiceError(f'{where}: {e}') from e
    try:
        description = vpp.read_description(ref.author_dir)
        bank = vpp.load_exemplars(ref.author_dir)
    except vpp.ProposalError as e:
        raise VoiceError(f'{where}: {e}. Make the description and the exemplars there '
                         f'(`storyforge voice propose`, then `voice accept`), or remove '
                         f'the book\'s `voice:` block') from e
    except FileNotFoundError as e:   # exemplars/ itself missing
        raise VoiceError(f'{where} has no {EXEMPLARS_DIR}/: make the exemplars there '
                         f'(`storyforge voice propose`, then `voice accept`)') from e
    if not description.strip():
        raise VoiceError(f'{where}: {DESCRIPTION_FILE} is empty')
    if not bank.exemplars:
        raise VoiceError(f'{where}: the exemplar bank ({EXEMPLARS_DIR}/exemplars.csv) holds '
                         f'no passage')
    notes = ''
    notes_path = os.path.join(project_dir, BOOK_NOTES)
    if os.path.isfile(notes_path):
        try:
            notes = _read(notes_path).strip()
        except (OSError, UnicodeDecodeError) as e:
            raise VoiceError(f'{BOOK_NOTES} can\'t be read ({e})') from e
    return BookVoice(ref, settings.author, description, bank, _anchor(ref),
                     os.path.join(ref.author_dir, FINGERPRINT_FILE), notes)


def require_voice(project_dir: str) -> list[str]:
    """Load the book's voice once, so a command stops on a bad one before it
    branches, forecasts or spends. Returns lines to log: what's read, and a
    WARNING for exemplar files the bank's index doesn't name (left out of
    the prompt). [] without a `voice:` block.

    Raises:
        VoiceError: as `book_voice`.
    """
    voice = book_voice(project_dir)
    if voice is None:
        return []
    bank = voice.exemplars
    who = voice.author or voice.ref.author
    lines = [f'Voice: {who} ({voice.ref.author}), read in place: the description, '
             f'{len(bank.exemplars)} exemplar(s)'
             + (f', the fiction anchor {voice.ref.narrator}' if voice.anchor else '')
             + (f', {BOOK_NOTES}' if voice.book_notes else '')]
    if bank.unlisted:
        lines.append(f'WARNING: {voice.ref.author}/{EXEMPLARS_DIR}/ holds '
                     f'{len(bank.unlisted)} file(s) its exemplars.csv doesn\'t name, left out '
                     f'of the drafting prompt: {", ".join(bank.unlisted[:10])}')
    return lines


#: what the drafting prompt says the author's voice is for
VOICE_PREAMBLE = (
    'This book is written in its author\'s own voice. Below, the voice is described, '
    'then shown in passages of the author\'s own prose. The passages are the voice '
    'spec: write as this writer writes, in their rhythm, diction and stance. Take '
    'the voice, never the content: don\'t reuse their subjects, names or sentences.')


def _demote(markdown: str, by: int = 2) -> str:
    """Headings `by` levels deeper, so a file's `#` sits under the prompt's
    section."""
    return re.sub(r'^(#{1,6}) ', lambda m: '#' * min(6, len(m.group(1)) + by) + ' ',
                  markdown, flags=re.MULTILINE)


def author_voice_section(project_dir: str) -> str:
    """The author's voice for the drafting prompt: the description, the
    exemplars by job, the fiction anchor and the book's own voice notes.
    '' without a `voice:` block.

    Raises:
        VoiceError: as `book_voice`.
    """
    voice = book_voice(project_dir)
    if voice is None:
        return ''
    parts = ['## The Author\'s Voice — Write Like This', VOICE_PREAMBLE,
             '### The voice, described', _demote(voice.description.strip())]
    parts.append('### The author\'s prose (exemplars)')
    for i, ex in enumerate(voice.exemplars.exemplars, start=1):
        note = f': {ex.why}' if ex.why else ''
        parts.append(f'#### Passage {i} ({ex.job}){note}\n\n{ex.text.strip()}')
    if voice.anchor:
        parts.append(f'### The narrator for this book (fiction anchor: {voice.ref.narrator})')
        parts.append('The author wrote or chose this fiction in their voice for this '
                     'narrator. Hold the narration to its stance, distance and tense.')
        parts.extend(_demote(text, 3) for _, text in voice.anchor)
    if voice.book_notes:
        parts.append(f'### This book\'s voice ({BOOK_NOTES})')
        parts.append(_demote(voice.book_notes))
    return '\n\n'.join(parts)
