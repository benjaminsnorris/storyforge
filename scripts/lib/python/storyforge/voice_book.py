"""The book's voice: `reference/voice/` (ready-to-draft plan, 2026-11-14).

The voice a book is written in is passages and notes that quote them, not a
rule list. *Wrath Like Smoke*'s voice rounds showed why: a sample written
from a list of things to avoid avoided all of them and read flat. So the
voice lives in three kinds of file, each for one job:

    reference/voice/
      book.md       # what the voice does, quoting the anchors; the people;
                    # decided rules (person, distance, tense). Read when writing.
      anchors/      # passages the author chose or finished by hand, one .md
                    # each. Read when writing: they are the voice spec.
      checks.md     # checks run on a finished scene. Never in a writing
                    # prompt (`writing_section` leaves it out): a reviewer
                    # reads it (`checks_text`).

An anchor may start with `key: value` lines before its first blank line:
`kind:` (what kind of scene it shows: intimate, battle, god, council... any
words, comma-separated), `tense:` and `pov:`. They tell the writer which
anchor is closest to a scene; nothing else reads them.

This replaces the pipeline's voice files: `voice-guide.md`,
`voice-profile.csv`, `persistent-prompt.md` and `prose-exemplars.md` (or
`exemplars/<pov>.md`) are no longer written or read. `old_voice_files` lists
any a book still has, so `status` and `cleanup` can say they're ignored; they
are never deleted (the author's text).

A book whose `storyforge.yaml` has a `voice:` block (an author voice repo,
`storyforge.voice_repo`) gets the author's description, exemplars and fiction
anchor first, then this folder. With an author repo, `book.md` and anchors
are optional; without one, the voice needs `book.md` and at least one anchor.

`resolve` is the one verdict every command shares (`status`'s voice rung,
`write`'s refusal, the drafting, revision, evaluation and hone prompts), as a
`common.DocState`: 'ok' with the writing section as `.text`, else why not.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from storyforge.common import DocState, ReferenceDocError, get_plugin_dir

VOICE_DIR = os.path.join('reference', 'voice')
BOOK_FILE = os.path.join(VOICE_DIR, 'book.md')
ANCHORS_DIR = os.path.join(VOICE_DIR, 'anchors')
CHECKS_FILE = os.path.join(VOICE_DIR, 'checks.md')
#: the keys an anchor's header may give
ANCHOR_KEYS = ('kind', 'tense', 'pov')
#: the values `scenes.csv`'s `tense` column takes (blank: not said)
TENSES = ('present', 'past')

#: what makes the voice, named wherever its absence is reported
REMEDY = (f'put at least one passage you chose or finished by hand in {ANCHORS_DIR}/ '
          f'and say what it does in {BOOK_FILE} (references/voice-folder.md; the '
          f'elaborate skill\'s voice stage runs sample rounds to find one)')

#: the pipeline's voice files, no longer written or read: (path, what it was)
OLD_FILES = (
    (os.path.join('reference', 'voice-guide.md'), 'the voice guide'),
    (os.path.join('reference', 'voice-profile.csv'), 'the voice profile'),
    (os.path.join('reference', 'persistent-prompt.md'), 'the persistent prompt'),
    (os.path.join('references', 'voice-guide.md'), 'the voice guide'),
    (os.path.join('reference', 'prose-exemplars.md'), 'the prose exemplars'),
    (os.path.join('reference', 'exemplars'), 'the per-POV prose exemplars'),
)


@dataclass(frozen=True)
class Anchor:
    """One anchor passage: its file (relative to the project), the header's
    keys, and the passage without the header."""
    path: str
    text: str
    kind: tuple[str, ...] = ()
    tense: str = ''
    pov: str = ''

    @property
    def name(self) -> str:
        return os.path.splitext(os.path.basename(self.path))[0]

    def label(self) -> str:
        """`name (kind: battle; tense: past)`, for a prompt's heading."""
        parts = []
        if self.kind:
            parts.append(f'kind: {", ".join(self.kind)}')
        if self.tense:
            parts.append(f'tense: {self.tense}')
        if self.pov:
            parts.append(f'POV: {self.pov}')
        return f'{self.name} ({"; ".join(parts)})' if parts else self.name


@dataclass(frozen=True)
class BookVoiceFolder:
    """What `reference/voice/` holds: `book.md`'s text ('' when missing,
    empty or still init's template), the anchors in file-name order, and
    `checks.md`'s text."""
    notes: str = ''
    anchors: tuple[Anchor, ...] = ()
    checks: str = ''
    #: anchor files left out, each with why (empty, or a header it can't read)
    skipped: tuple[str, ...] = field(default_factory=tuple)


def _template(rel: str) -> str:
    """init's template for a file in the voice folder ('' without one)."""
    path = os.path.join(get_plugin_dir(), 'templates', rel)
    try:
        with open(path, encoding='utf-8-sig') as f:
            return f.read().strip()
    except OSError:
        return ''


def _read(project_dir: str, rel: str) -> str:
    """A voice file's text, stripped: '' when missing, empty or still init's
    template.

    Raises:
        ReferenceDocError: the file exists but can't be read.
    """
    path = os.path.join(project_dir, rel)
    if not os.path.isfile(path):
        return ''
    try:
        with open(path, encoding='utf-8-sig') as f:
            text = f.read().strip()
    except (OSError, UnicodeDecodeError) as e:
        raise ReferenceDocError(path, e) from e
    template = _template(rel)
    if template and text.replace('\r\n', '\n') == template.replace('\r\n', '\n'):
        return ''
    return text


_HEADER = re.compile(r'^(\w+):\s*(.*)$')


def parse_anchor(rel: str, raw: str) -> Anchor:
    """An anchor from its file's text. Header lines (`kind:`, `tense:`,
    `pov:`) are read only at the very top, before the first blank line, and
    only when every line there is one of them; otherwise the whole file is
    the passage.

    Raises:
        ValueError: the header gives a key twice or a tense that isn't
            present or past; the passage is empty.
    """
    text = raw.replace('\r\n', '\n').strip()
    head, sep, body = text.partition('\n\n')
    lines = [ln.strip() for ln in head.split('\n')]
    matches = [_HEADER.match(ln) for ln in lines]
    keys: dict[str, str] = {}
    if all(m and m.group(1).lower() in ANCHOR_KEYS for m in matches):
        # a header (with no passage after it, the passage is empty)
        for m in matches:
            key = m.group(1).lower()
            if key in keys:
                raise ValueError(f'{rel}: `{key}:` is given twice')
            keys[key] = m.group(2).strip()
        text = body.strip()
    if not text:
        raise ValueError(f'{rel}: the passage is empty')
    tense = keys.get('tense', '').lower()
    if tense and tense not in TENSES:
        raise ValueError(f'{rel}: tense {keys["tense"]!r} is not one of {", ".join(TENSES)}')
    kind = tuple(k.strip().lower() for k in keys.get('kind', '').split(',') if k.strip())
    return Anchor(rel, text, kind, tense, keys.get('pov', ''))


def read_folder(project_dir: str) -> BookVoiceFolder:
    """`reference/voice/` as it stands (everything empty without it).

    Raises:
        ReferenceDocError: book.md, checks.md or an anchor exists but can't be
            read.
    """
    notes = _read(project_dir, BOOK_FILE)
    checks = _read(project_dir, CHECKS_FILE)
    anchors, skipped = [], []
    folder = os.path.join(project_dir, ANCHORS_DIR)
    if os.path.isdir(folder):
        for name in sorted(os.listdir(folder)):
            path = os.path.join(folder, name)
            if not name.lower().endswith('.md') or not os.path.isfile(path):
                continue
            rel = os.path.join(ANCHORS_DIR, name)
            try:
                with open(path, encoding='utf-8-sig') as f:
                    raw = f.read()
            except (OSError, UnicodeDecodeError) as e:
                raise ReferenceDocError(path, e) from e
            try:
                anchors.append(parse_anchor(rel, raw))
            except ValueError as e:
                skipped.append(str(e))
    return BookVoiceFolder(notes, tuple(anchors), checks, tuple(skipped))


def old_voice_files(project_dir: str) -> list[tuple[str, str]]:
    """The pipeline's voice files this book still has, none of which is read
    any more: (path, what it was)."""
    return [(rel, what) for rel, what in OLD_FILES
            if os.path.exists(os.path.join(project_dir, rel))]


def old_files_note(project_dir: str) -> str:
    """One line naming the old voice files a book still has ('' without
    any): they're ignored, never deleted."""
    old = old_voice_files(project_dir)
    if not old:
        return ''
    names = ', '.join(rel for rel, _ in old)
    return (f'{names} {"is" if len(old) == 1 else "are"} no longer read: the voice is '
            f'{VOICE_DIR}/. Move what you want to keep into {BOOK_FILE} or an anchor, then '
            f'delete {"it" if len(old) == 1 else "them"}')


#: what a writing prompt says the voice section is for
PREAMBLE = (
    'This is the voice the book is written in. The passages are the spec: write toward '
    'them, in their rhythm, diction, distance and stance. The notes say what the '
    'passages do, quoting them. Take the voice, never the content: don\'t reuse their '
    'events or sentences.')


def _demote(markdown: str, by: int) -> str:
    return re.sub(r'^(#{1,6}) ', lambda m: '#' * min(6, len(m.group(1)) + by) + ' ',
                  markdown, flags=re.MULTILINE)


def render(folder: BookVoiceFolder, author_section: str = '') -> str:
    """The voice for a writing prompt: the author repo's section (when the
    book has one), then `book.md` and the anchors. Never `checks.md`."""
    parts = ['## The Voice — Write Like This', PREAMBLE]
    if author_section:
        parts.append(author_section)
    if folder.notes:
        parts.append('### What the voice does (reference/voice/book.md)')
        parts.append(_demote(folder.notes, 3))
    if folder.anchors:
        parts.append('### The anchors')
        for a in folder.anchors:
            parts.append(f'#### {a.label()}\n\n{a.text}')
    return '\n\n'.join(parts)


def resolve(project_dir: str) -> DocState:
    """The book's voice, as one verdict: 'ok' (`.text` the writing section,
    `.path` the voice folder), or 'missing', 'template', 'empty' or
    'unreadable' with `.detail` saying why. Without an author repo the voice
    needs `book.md` and an anchor; with one (the `voice:` block), the repo's
    voice is enough. A `voice:` block that can't be used raises
    `voice_repo.VoiceError`, as it always has.
    """
    from storyforge.voice_repo import author_voice_section, voice_ref
    try:
        folder = read_folder(project_dir)
    except ReferenceDocError as e:
        rel = os.path.relpath(e.path, project_dir) if os.path.isabs(e.path) else e.path
        return DocState('unreadable', rel, f"can't read {rel}: {e.__cause__}")
    author = author_voice_section(project_dir) if voice_ref(project_dir) else ''
    if author or (folder.notes and folder.anchors):
        return DocState('ok', VOICE_DIR, VOICE_DIR, render(folder, author))
    book = os.path.join(project_dir, BOOK_FILE)
    if not os.path.isfile(book) and not folder.anchors:
        return DocState('missing', '', f'{VOICE_DIR}/ has no voice yet')
    if not folder.notes:
        kind = 'template' if is_template(project_dir, BOOK_FILE) else 'empty'
        what = "still init's template" if kind == 'template' else 'missing or empty'
        return DocState(kind, BOOK_FILE, f'{BOOK_FILE} is {what}')
    skipped = f' ({"; ".join(folder.skipped)})' if folder.skipped else ''
    return DocState('empty', ANCHORS_DIR, f'{ANCHORS_DIR}/ holds no anchor passage{skipped}')


def checks_text(project_dir: str) -> str:
    """`checks.md`'s text, for a reviewer ('' without one).

    Raises:
        ReferenceDocError: it exists but can't be read.
    """
    return _read(project_dir, CHECKS_FILE)


def register_section(project_dir: str, heading: str) -> str:
    """The body of `book.md`'s `## <heading>` section ('' without one).

    Raises:
        ReferenceDocError: book.md exists but can't be read.
    """
    text = _read(project_dir, BOOK_FILE)
    m = re.search(rf'^##\s+{re.escape(heading)}\s*$(.*?)(?=^##\s|\Z)', text,
                  flags=re.MULTILINE | re.DOTALL | re.IGNORECASE)
    return m.group(1).strip() if m else ''


# ============================================================================
# Tense (free, code only)
# ============================================================================

#: Common verbs in narration, third person: (present, past). Closed lists,
#: so a plural noun ("looks", "turns") is the only false signal, and it's
#: rare beside these
_VERBS = (
    ('is', 'was'), ('are', 'were'), ('has', 'had'), ('does', 'did'), ('says', 'said'),
    ('sees', 'saw'), ('comes', 'came'), ('goes', 'went'), ('takes', 'took'),
    ('knows', 'knew'), ('thinks', 'thought'), ('looks', 'looked'), ('turns', 'turned'),
    ('feels', 'felt'), ('stands', 'stood'), ('sits', 'sat'), ('holds', 'held'),
    ('gets', 'got'), ('makes', 'made'), ('gives', 'gave'), ('finds', 'found'),
    ('tells', 'told'), ('hears', 'heard'), ('leaves', 'left'), ('runs', 'ran'),
    ('falls', 'fell'), ('walks', 'walked'), ('waits', 'waited'), ('reaches', 'reached'),
    ('lifts', 'lifted'), ('watches', 'watched'), ('opens', 'opened'), ('begins', 'began'),
    ('keeps', 'kept'), ('brings', 'brought'), ('lies', 'lay'), ('speaks', 'spoke'),
    ('rises', 'rose'), ('wants', 'wanted'), ('seems', 'seemed'), ('stops', 'stopped'),
)
_PRESENT = {p for p, _ in _VERBS}
_PAST = {p for _, p in _VERBS}
#: speech, which is as people speak: straight, curly and single-curly quotes
_SPEECH = re.compile(r'"[^"\n]*"|“[^”]*”|‘[^’\n]*’(?!\w)')
_WORD = re.compile(r"[A-Za-z]+")
#: how many verb forms a scene needs before its tense is judged
MIN_TENSE_SIGNALS = 12
#: the share of the other tense's forms that makes a finding: present-tense
#: narration still says "had" and "was" for what came before, so well past
#: half
TENSE_MISMATCH_SHARE = 0.75


@dataclass(frozen=True)
class TenseReading:
    """What the narration's verbs say: counts of each tense's forms."""
    present: int
    past: int

    @property
    def total(self) -> int:
        return self.present + self.past

    def share(self, tense: str) -> float:
        return (self.present if tense == 'present' else self.past) / self.total if self.total else 0.0


def read_tense(prose: str) -> TenseReading:
    """Counts of present and past forms in the narration (speech left out)."""
    narration = _SPEECH.sub(' ', prose)
    words = [w.lower() for w in _WORD.findall(narration)]
    return TenseReading(sum(w in _PRESENT for w in words), sum(w in _PAST for w in words))


def tense_problem(prose: str, declared: str) -> str:
    """Why the narration isn't in the `declared` tense, or '' when it is, the
    scene declares none, or there are too few verb forms to tell (said as
    '' too: a scene under `MIN_TENSE_SIGNALS` isn't judged)."""
    declared = (declared or '').strip().lower()
    if declared not in TENSES:
        return ''
    reading = read_tense(prose)
    if reading.total < MIN_TENSE_SIGNALS:
        return ''
    other = 'past' if declared == 'present' else 'present'
    if reading.share(other) >= TENSE_MISMATCH_SHARE:
        return (f'scenes.csv says this scene is told in the {declared} tense, but '
                f'{reading.share(other):.0%} of the narration\'s common verb forms are '
                f'{other} ({reading.present} present, {reading.past} past)')
    return ''


# ============================================================================
# Setting up the folder
# ============================================================================

#: the folder's files init and the voice stage copy from templates/
SCAFFOLD = (BOOK_FILE, CHECKS_FILE, os.path.join(ANCHORS_DIR, '.gitkeep'))


def scaffold(project_dir: str, dry_run: bool = False) -> list[str]:
    """Copy the voice folder's missing files from the templates (never over
    a file that's there). Returns what was (or, dry, would be) made,
    relative to the project."""
    made = []
    for rel in SCAFFOLD:
        path = os.path.join(project_dir, rel)
        # anchors/.gitkeep only keeps an empty folder in git
        if os.path.exists(path) or (os.path.basename(rel) == '.gitkeep'
                                    and os.path.isdir(os.path.dirname(path))):
            continue
        made.append(rel)
        if dry_run:
            continue
        os.makedirs(os.path.dirname(path), exist_ok=True)
        template = os.path.join(get_plugin_dir(), 'templates', rel)
        with open(template, encoding='utf-8') as f:
            text = f.read()
        with open(path, 'w', encoding='utf-8') as f:
            f.write(text)
    return made


def is_template(project_dir: str, rel: str) -> bool:
    """Whether a file in the voice folder is still init's template (a file
    outside it, or with no template, never is)."""
    rel = os.path.normpath(rel)
    if not rel.startswith(VOICE_DIR + os.sep):
        return False
    template = _template(rel)
    if not template:
        return False
    try:
        with open(os.path.join(project_dir, rel), encoding='utf-8-sig') as f:
            text = f.read().strip()
    except (OSError, UnicodeDecodeError):
        return False
    return text.replace('\r\n', '\n') == template.replace('\r\n', '\n')
