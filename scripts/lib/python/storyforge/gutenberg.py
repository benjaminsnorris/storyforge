"""Project Gutenberg texts as Storyforge manuscripts (`storyforge source fetch`).

Fetches an ebook's plain text, strips the Gutenberg header and licence, and
normalizes the work into a manuscript that `scenes-setup --split-manuscript`
can split: `# <heading>` chapter and part headings, `* * *` scene breaks, and
one paragraph per line. Deterministic: no model calls.

Ported from the storyforge-evals harness (`harness/prepare_corpus.py`), which
prepared the thirteen evals books; every option it had is kept and gives the
same manuscript for the same raw text.

The config is a JSON object (`reference/gutenberg.json` in a project, or the
evals repo's `corpus/<slug>/meta.json`). Text keys (see `TEXT_KEYS`):

  gutenberg_id     ebook number
  chapter_heading  regex matching a chapter heading line in the raw text
  heading          format for the cleaned heading, filled from the regex
                   groups (default "Chapter {}")
  part_heading     regex matching a part (volume, book) heading line
  part_format      format for the cleaned part heading (default "Part {}")
  part_title       true when a part heading's title sits on the next line
                   ("BOOK I." then "MISS BROOKE." -> "Book I: Miss Brooke")
  section_heading  regex for a section heading inside a chapter ("I", or a
                   titled section); the line is dropped, and each becomes a
                   scene break except the chapter's first, which the chapter
                   heading already starts
  section_break    how section headings break scenes. true (the default):
                   all but the chapter's first. "after_text": every one with
                   text before it in its chapter, so a first section that
                   follows untitled paragraphs gets its break (Weston's
                   Fitts II and IV); not the default because The Brimming
                   Cup's chapter titles stand before its first section.
                   false: none, the heading lines are only dropped (titles
                   that fall more often than scenes do)
  skip_from        list of regexes; a matching line starts a run of dropped
                   lines that ends at the next chapter or part heading
  other_headings   {regex: heading} for unnumbered chapters ("PRELUDE." ->
                   "Prelude")
  drop_argument    true drops the first paragraph after each chapter heading
                   (a translator's summary)
  note_marker      regex for footnote markers, removed from the text
  note_paragraph   regex; a paragraph whose first line matches is dropped
  chapter_title    true when a chapter's title runs on the lines right after
                   its heading ("CHAPTER I." then "IN WHICH ...")
  heading_case     "title" title-cases the groups filled into the heading
  verse            true keeps the text's line breaks (see below)
  drop_cap_case    "title" title-cases an all-capitals first word opening a
                   chapter ("LO," -> "Lo,", "HROTHGAR" -> "Hrothgar"): the
                   printed drop capital, which extraction would quote
  strip_brackets   true removes square brackets and keeps their words
                   (Gummere's restorations of the damaged manuscript)
  strip_unmatched_underscore
                   true drops an `_` with no partner in its paragraph, which
                   would otherwise italicize the rest of it
  verse_blocks     prose only: true keeps the line breaks of a paragraph whose
                   lines are all indented (a poem quoted in prose: Weston's
                   closing bob-and-wheel), as verse mode does

Descriptive keys (`DESCRIPTIVE_KEYS`: title, author, year, genre, ...) are
read by `storyforge init`; fetch ignores them. Any other key is an error, so
a misspelt option can't silently do nothing.

Verse mode. Prose joins each paragraph onto one line, which destroys verse.
With `verse`, every line of the text stays a line: each line but a stanza's
(or verse paragraph's) last ends in a backslash, markdown's hard line break
(pandoc and CommonMark both read `\\` before a newline as `<br>`), and a
blank line still separates stanzas. The backslash sits on the line's last
word, so word counts don't change. Leading indentation is dropped (four
spaces would start a markdown code block).
"""

from __future__ import annotations

import http.client
import json
import os
import re
import urllib.request

GUTENBERG_URL = 'https://www.gutenberg.org/cache/epub/{id}/pg{id}.txt'
START_RE = re.compile(r'^\*\*\* ?START OF (?:THE|THIS) PROJECT GUTENBERG EBOOK')
END_RE = re.compile(r'^\*\*\* ?END OF (?:THE|THIS) PROJECT GUTENBERG EBOOK')

# A verse line's hard break: a backslash ending the line
HARD_BREAK = '\\'

TEXT_KEYS = frozenset({
    'gutenberg_id', 'chapter_heading', 'heading', 'part_heading', 'part_format',
    'part_title', 'section_heading', 'skip_from', 'other_headings',
    'drop_argument', 'note_marker', 'note_paragraph', 'chapter_title',
    'heading_case', 'verse', 'section_break', 'verse_blocks', 'drop_cap_case',
    'strip_brackets', 'strip_unmatched_underscore',
})
DESCRIPTIVE_KEYS = frozenset({
    'slug', 'title', 'author', 'year', 'genre', 'subgenre', 'logline',
    'edition', 'set', 'translator', 'form',
})

# Where a project keeps the config and the raw download
CONFIG_REL = os.path.join('reference', 'gutenberg.json')
CACHE_DIR_REL = os.path.join('working', 'gutenberg')


class GutenbergError(Exception):
    """A config, download or text that can't make a manuscript."""


# ============================================================================
# Config
# ============================================================================

def check_config(meta: dict) -> dict:
    """The config, checked: a dict with a chapter_heading, known keys only,
    and regexes that compile. Raises GutenbergError naming the problem."""
    if not isinstance(meta, dict):
        raise GutenbergError('the config must be a JSON object')
    unknown = sorted(set(meta) - TEXT_KEYS - DESCRIPTIVE_KEYS)
    if unknown:
        raise GutenbergError(
            f'unknown config key(s): {", ".join(unknown)} (known: '
            f'{", ".join(sorted(TEXT_KEYS | DESCRIPTIVE_KEYS))})')
    if not meta.get('chapter_heading'):
        raise GutenbergError('the config has no chapter_heading regex')
    _check_types(meta)
    regexes = [('chapter_heading', meta['chapter_heading'])]
    for key in ('part_heading', 'section_heading', 'note_marker', 'note_paragraph'):
        if meta.get(key):
            regexes.append((key, meta[key]))
    for r in meta.get('skip_from', []) or []:
        regexes.append(('skip_from', r))
    for r in (meta.get('other_headings') or {}):
        regexes.append(('other_headings', r))
    for key, pattern in regexes:
        try:
            re.compile(pattern)
        except (re.error, TypeError) as e:
            raise GutenbergError(f'{key} regex {pattern!r} does not compile: {e}')
    if meta.get('section_break', True) not in (True, False, 'after_text'):
        raise GutenbergError('section_break must be true, false or "after_text", '
                             f'not {meta["section_break"]!r}')
    if meta.get('drop_cap_case') not in (None, '', 'title'):
        raise GutenbergError(f'drop_cap_case must be "title", not {meta["drop_cap_case"]!r}')
    if meta.get('heading_case') not in (None, '', 'title'):
        raise GutenbergError(f'heading_case must be "title", not {meta["heading_case"]!r}')
    _check_format(meta, 'heading', 'Chapter {}', 'chapter_heading')
    _check_format(meta, 'part_format', 'Part {}', 'part_heading')
    return meta


_STRING_KEYS = ('chapter_heading', 'heading', 'part_heading', 'part_format',
                'section_heading', 'note_marker', 'note_paragraph')
_BOOL_KEYS = ('part_title', 'drop_argument', 'chapter_title', 'verse', 'verse_blocks',
              'strip_brackets', 'strip_unmatched_underscore')


def _check_types(meta: dict) -> None:
    """Each text key's value has its type: a string `skip_from` was read
    letter by letter and emptied the manuscript without an error."""
    for key in _STRING_KEYS:
        if meta.get(key) is not None and not isinstance(meta[key], str):
            raise GutenbergError(f'{key} must be a string, not {meta[key]!r}')
    for key in _BOOL_KEYS:
        if key in meta and not isinstance(meta[key], bool):
            raise GutenbergError(f'{key} must be true or false, not {meta[key]!r}')
    skip = meta.get('skip_from')
    if skip is not None and not (isinstance(skip, list)
                                 and all(isinstance(r, str) for r in skip)):
        raise GutenbergError(f'skip_from must be a list of regexes, not {skip!r}')
    others = meta.get('other_headings')
    if others is not None and not (isinstance(others, dict) and all(
            isinstance(k, str) and isinstance(v, str) for k, v in others.items())):
        raise GutenbergError('other_headings must be an object of {regex: heading}, '
                             f'not {others!r}')
    ebook_id = meta.get('gutenberg_id')
    if ebook_id is not None and (isinstance(ebook_id, bool)
                                 or not re.fullmatch(r'\d+', str(ebook_id))):
        raise GutenbergError(f'gutenberg_id must be an ebook number, not {ebook_id!r}')


def _check_format(meta: dict, key: str, default: str, regex_key: str) -> None:
    """The heading format takes the regex's groups (or the whole line when
    it has none)."""
    if not meta.get(regex_key):
        return
    groups = re.compile(meta[regex_key]).groups or 1
    fmt = meta.get(key, default)
    try:
        fmt.format(*(['x'] * groups))
    except (IndexError, KeyError, ValueError) as e:
        raise GutenbergError(f'{key} {fmt!r} does not fit {regex_key}\'s {groups} '
                             f'group(s): {e}')


def read_config(path: str) -> dict:
    """Read and check a JSON config file."""
    try:
        with open(path, encoding='utf-8') as f:
            meta = json.load(f)
    except OSError as e:
        raise GutenbergError(f'cannot read {path}: {e.strerror}')
    except json.JSONDecodeError as e:
        raise GutenbergError(f'{path} is not valid JSON: {e}')
    return check_config(meta)


# ============================================================================
# Fetch
# ============================================================================

def download(ebook_id) -> bytes:
    """Ebook `ebook_id`'s plain text, as Gutenberg serves it."""
    url = GUTENBERG_URL.format(id=ebook_id)
    req = urllib.request.Request(url, headers={'User-Agent': 'storyforge'})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.read()
    except (OSError, http.client.HTTPException) as e:
        # HTTPException: a cut-off download (IncompleteRead) isn't an OSError
        raise GutenbergError(f'cannot download {url}: {e!r}')


# ============================================================================
# Normalize
# ============================================================================

def strip_boilerplate(lines: list[str]) -> list[str]:
    """The lines between Gutenberg's START and END markers."""
    start = next((i for i, l in enumerate(lines) if START_RE.match(l)), None)
    end = next((i for i, l in enumerate(lines) if END_RE.match(l)), None)
    if start is None or end is None or end <= start:
        raise GutenbergError('no "*** START OF THE PROJECT GUTENBERG EBOOK" / '
                             '"*** END OF ..." markers: not a Gutenberg plain text')
    return lines[start + 1:end]


def title_words(text: str) -> str:
    """Title-case word by word, unlike str.title(), which capitalizes after an
    apostrophe ("FOGG’S" -> "Fogg’S")."""
    def word(w):
        w = w.lower()
        m = re.search(r'[a-z]', w)
        return w[:m.start()] + w[m.start()].upper() + w[m.start() + 1:] if m else w
    return ' '.join(word(w) for w in text.split())


_DROP_CAP_RE = re.compile(r"^([^\w]*)([A-Z][A-Z'’]+)\b")


def drop_cap_word(text: str) -> str:
    """An all-capitals first word (two letters or more) title-cased."""
    return _DROP_CAP_RE.sub(lambda m: m.group(1) + m.group(2)[0] + m.group(2)[1:].lower(),
                            text, count=1)


def drop_unmatched_underscores(text: str) -> str:
    """`text` without an emphasis `_` that has no partner. An `_` opens
    after a non-word character and before a non-space; it closes after a
    non-space and before a non-word character; an `_` inside a word
    (snake_case) is left alone."""
    drop, open_at = [], None
    for m in re.finditer(r'_+', text):
        i, j = m.start(), m.end()
        before = text[i - 1] if i else ' '
        after = text[j] if j < len(text) else ' '
        if before.isalnum() and after.isalnum():
            continue
        can_open = not before.isalnum() and not after.isspace()
        can_close = not before.isspace() and not after.isalnum()
        if open_at is not None and can_close:
            open_at = None
        elif can_open:
            if open_at is not None:
                drop.append(open_at)
            open_at = (i, j)
        else:
            drop.append((i, j))
    if open_at is not None:
        drop.append(open_at)
    for i, j in sorted(drop, reverse=True):
        text = text[:i] + text[j:]
    return text


def normalize(raw: str, meta: dict) -> str:
    """The manuscript for a raw Gutenberg text under config `meta`."""
    lines = strip_boilerplate(raw.replace('\r\n', '\n').split('\n'))
    heading_re = re.compile(meta['chapter_heading'])
    part_re = re.compile(meta['part_heading']) if meta.get('part_heading') else None
    section_re = re.compile(meta['section_heading']) if meta.get('section_heading') else None
    skip_res = [re.compile(r) for r in meta.get('skip_from', []) or []]
    others = [(re.compile(r), h) for r, h in (meta.get('other_headings') or {}).items()]
    part_title = meta.get('part_title', False)
    drop_argument = meta.get('drop_argument', False)
    note_re = re.compile(meta['note_marker']) if meta.get('note_marker') else None
    note_para_re = re.compile(meta['note_paragraph']) if meta.get('note_paragraph') else None
    chapter_title = meta.get('chapter_title', False)
    title_case = meta.get('heading_case') == 'title'
    verse = bool(meta.get('verse', False))
    verse_blocks = bool(meta.get('verse_blocks', False))
    section_break = meta.get('section_break', True)
    drop_cap = meta.get('drop_cap_case') == 'title'
    strip_brackets = bool(meta.get('strip_brackets', False))
    strip_underscore = bool(meta.get('strip_unmatched_underscore', False))

    # A heading counts only when surrounded by blank lines; this skips
    # table-of-contents entries, which sit on consecutive lines.
    def is_heading(i, regex=heading_re):
        if not regex or not regex.match(lines[i]):
            return False
        before = i == 0 or not lines[i - 1].strip()
        if chapter_title and regex is heading_re:
            # "CHAPTER I." then its title, then a blank line
            return before and i + 1 < len(lines) and bool(lines[i + 1].strip())
        after = i + 1 >= len(lines) or not lines[i + 1].strip()
        return before and after

    def is_part(i):
        if part_title and part_re and part_re.match(lines[i]) and i + 2 < len(lines):
            # "BOOK I." then "MISS BROOKE.", then a blank line
            before = i == 0 or not lines[i - 1].strip()
            return before and bool(lines[i + 1].strip()) and not lines[i + 2].strip()
        return is_heading(i, part_re)

    def other(i):
        return next((h for r, h in others if is_heading(i, r)), None)

    first = next((i for i in range(len(lines)) if is_heading(i) or is_part(i) or other(i)),
                 None)
    if first is None:
        raise GutenbergError('no line matches chapter_heading (or part_heading, '
                             'other_headings) between blank lines; check the regex '
                             'against the raw text')

    out, para = [], []
    indented = []  # per line of para: did it start with whitespace
    skipping = False
    first_section = True
    chapter_text = False  # text in this chapter yet (section_break "after_text")
    drop_next = False

    def clean(text):
        # Gutenberg's ASCII opening single quote (`father') is a markdown
        # code span: published in monospace with a space lost (F-158)
        text = text.replace('`', "'")
        text = note_re.sub('', text) if note_re else text
        if strip_brackets:
            text = text.replace('[', '').replace(']', '')
        return text

    def flush():
        nonlocal drop_next
        nonlocal chapter_text
        if para and drop_next:
            para.clear()
            drop_next = False
        if para and note_para_re and note_para_re.match(para[0]):
            para.clear()
        lineate = verse or (verse_blocks and len(para) > 1 and all(indented))
        indented.clear()
        if para:
            if lineate:
                verse_lines = [clean(l).rstrip() for l in para]
                text = (HARD_BREAK + '\n').join(l for l in verse_lines if l)
            else:
                text = clean(' '.join(para))
            if strip_underscore:
                text = drop_unmatched_underscores(text)
            if drop_cap and not chapter_text:
                text = drop_cap_word(text)
            chapter_text = True
            out.append(text)
            out.append('')
            para.clear()

    title_line = None
    title_end = -1
    for i in range(first, len(lines)):
        stripped = lines[i].strip()
        if i == title_line or i <= title_end:
            continue
        if is_part(i):
            flush()
            skipping = False
            groups = part_re.match(lines[i]).groups() or (stripped,)
            heading = meta.get('part_format', 'Part {}').format(*groups)
            if part_title:
                title_line = i + 1
                heading += ': ' + lines[i + 1].strip().rstrip('.').title()
            out.extend(['# ' + heading, ''])
        elif other(i):
            flush()
            skipping = False
            out.extend(['# ' + other(i), ''])
            first_section = True
            chapter_text = False
        elif is_heading(i):
            flush()
            skipping = False
            groups = heading_re.match(lines[i]).groups() or (stripped,)
            if title_case:
                groups = tuple(title_words(g) for g in groups)
            heading = meta.get('heading', 'Chapter {}').format(*groups)
            if chapter_title:
                title_end = i + 1
                while title_end + 1 < len(lines) and lines[title_end + 1].strip():
                    title_end += 1
                title = ' '.join(l.strip() for l in lines[i + 1:title_end + 1])
                heading += ': ' + title_words(title.rstrip('.'))
            out.extend(['# ' + heading, ''])
            first_section = True
            chapter_text = False
            drop_next = drop_argument
        elif skipping:
            continue
        elif is_heading(i, section_re):
            flush()
            if section_break == 'after_text':
                if chapter_text:
                    out.extend(['* * *', ''])
                chapter_text = False
            elif section_break and not first_section:
                out.extend(['* * *', ''])
            first_section = False
            continue
        elif any(r.match(stripped) for r in skip_res):
            flush()
            skipping = True
        elif not stripped:
            flush()
        else:
            para.append(stripped)
            indented.append(lines[i][:1] in (' ', '\t'))
    flush()
    # A break rule left at the very end (before dropped end matter) ends nothing.
    while out and (not out[-1] or re.fullmatch(r'(?:[*\-]\s*){3,}', out[-1])):
        out.pop()
    return '\n'.join(out).rstrip() + '\n'


def summarize(manuscript: str, meta: dict) -> dict:
    """Counts for the run's report: words, chapter and part headings, breaks,
    and verse lines."""
    lines = manuscript.splitlines()
    part_prefix = '# ' + meta.get('part_format', 'Part {}').split('{')[0]
    headings = [l for l in lines if l.startswith('# ')]
    parts = [l for l in headings if meta.get('part_heading') and l.startswith(part_prefix)]
    return {
        'words': len(manuscript.split()),
        'chapters': len(headings) - len(parts),
        'parts': len(parts),
        'breaks': sum(1 for l in lines if re.fullmatch(r'-{10,}|(?:\*\s*){3,}', l)),
        # in verse, every text line is a verse line
        'verse_lines': (sum(1 for l in lines if l.strip() and not l.startswith('# ')
                            and not re.fullmatch(r'-{10,}|(?:\*\s*){3,}', l))
                        if meta.get('verse') else 0),
    }



# ============================================================================
# A project's manuscript
# ============================================================================

MANUSCRIPT_REL = 'manuscript.md'


class Fetched:
    """A manuscript built for a project, not yet written: the config that
    made it, the raw text and where it is cached, and the manuscript."""

    def __init__(self, meta: dict, raw: bytes, raw_rel: str, manuscript: str,
                 downloaded: bool = False):
        self.meta = meta
        self.downloaded = downloaded
        self.raw = raw
        self.raw_rel = raw_rel
        self.manuscript = manuscript
        self.stats = summarize(manuscript, meta)


def build(project_dir: str, meta: dict, input_path: str | None = None,
          refresh: bool = False) -> Fetched:
    """Build the manuscript for `project_dir` under `meta`, writing nothing
    in the project. The raw text comes from `input_path`, else the project's
    cached download (`working/gutenberg/pg<id>.txt`), else Gutenberg
    (always Gutenberg with `refresh`)."""
    check_config(meta)
    ebook_id = meta.get('gutenberg_id')
    if ebook_id is not None and not re.fullmatch(r'\d+', str(ebook_id)):
        raise GutenbergError(f'gutenberg_id must be an ebook number, not {ebook_id!r}')
    if input_path is None and ebook_id is None:
        raise GutenbergError('no gutenberg_id in the config (or --gutenberg), '
                             'and no --input text')
    raw_rel = os.path.join(CACHE_DIR_REL, f'pg{ebook_id}.txt' if ebook_id is not None
                           else 'source.txt')
    cached = os.path.join(project_dir, raw_rel)
    if input_path is not None or (os.path.isfile(cached) and not refresh):
        src = input_path if input_path is not None else cached
        try:
            with open(src, 'rb') as f:
                raw = f.read()
        except OSError as e:
            raise GutenbergError(f'cannot read {src}: {e.strerror}')
    else:
        src = GUTENBERG_URL.format(id=ebook_id)
        raw = download(ebook_id)
    return Fetched(meta, raw, raw_rel, normalize(_decode(raw, src), meta),
                   downloaded=input_path is None and src != cached)


def _decode(raw: bytes, where) -> str:
    try:
        return raw.decode('utf-8-sig')
    except UnicodeDecodeError as e:
        raise GutenbergError(f'{where} is not UTF-8 ({e}); Gutenberg serves UTF-8 '
                             'at the cache/epub URL')


def config_text(meta: dict) -> str:
    return json.dumps(meta, indent=2, ensure_ascii=False) + '\n'


def plan_writes(project_dir: str, fetched: Fetched, force: bool = False) -> dict:
    """`{rel_path: bytes}` for each file the fetch would change. Raises
    GutenbergError, before anything is written, when without `force` it
    would replace a manuscript.md that differs, or a cached raw text with a
    different `--input` file (a fresh download, `--refresh`, replaces the
    cache: that is what it is for). A changed config is the caller's to
    report (`replaced`)."""
    files = {
        MANUSCRIPT_REL: fetched.manuscript.encode('utf-8'),
        CONFIG_REL: config_text(fetched.meta).encode('utf-8'),
        fetched.raw_rel: fetched.raw,
    }
    changes = {}
    for rel, data in files.items():
        path = os.path.join(project_dir, rel)
        if os.path.isfile(path):
            with open(path, 'rb') as f:
                if f.read() == data:
                    continue
            if rel == MANUSCRIPT_REL and not force:
                raise GutenbergError(
                    'manuscript.md exists and differs from the fetched text; '
                    '--force replaces it (scene files are never touched)')
            if rel == fetched.raw_rel and not force and not fetched.downloaded:
                raise GutenbergError(
                    f'{rel} holds a different raw text than --input; --force '
                    'replaces it')
        changes[rel] = data
    return changes


def replaced(project_dir: str, changes: dict) -> list[str]:
    """The files in `changes` that exist now: what a write replaces."""
    return sorted(rel for rel in changes if os.path.isfile(os.path.join(project_dir, rel)))


def write_files(project_dir: str, changes: dict) -> None:
    for rel, data in changes.items():
        path = os.path.join(project_dir, rel)
        os.makedirs(os.path.dirname(path) or project_dir, exist_ok=True)
        with open(path, 'wb') as f:
            f.write(data)


def describe(stats: dict) -> str:
    text = (f'{stats["words"]} words, {stats["chapters"]} chapters'
            + (f', {stats["parts"]} parts' if stats['parts'] else '')
            + f', {stats["breaks"]} scene breaks')
    if stats['verse_lines']:
        text += f', {stats["verse_lines"]} verse lines'
    return text
