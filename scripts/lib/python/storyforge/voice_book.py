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
                    # prompt (`render` leaves it out, and `read_folder`
                    # doesn't read it): `checks_text` gives it to a reviewer
                    # (the writing session's voice review, #655).

An anchor may start with `key: value` lines before its first blank line:
`kind:` (what kind of scene it shows: intimate, battle, god, council... any
words, comma-separated), `tense:` and `pov:`. They tell the writer which
anchor is closest to a scene; nothing else reads them.

This replaces the pipeline's voice files: `voice-guide.md`,
`voice-profile.csv`, `persistent-prompt.md` and `prose-exemplars.md` (or
`exemplars/<pov>.md`) are no longer written or read in a prose book.
`old_voice_files` lists any a book still has, so `status`, `write`,
`revise`, `evaluate`, `validate`, the voice stage and `cleanup` can say
they're ignored; they are never deleted (the author's text). A graphic
novel keeps its voice-guide.md and voice-profile.csv.

A book whose `storyforge.yaml` has a `voice:` block (an author voice repo,
`storyforge.voice_repo`) gets the author's description, exemplars and fiction
anchor first, then this folder. With an author repo, `book.md` and anchors
are optional; without one, the voice needs `book.md` and at least one anchor.

`resolve` is the one verdict every command shares (`status`'s voice rung,
`write`'s refusal, the drafting, revision, evaluation and hone prompts), as a
`common.DocState`: 'ok' with the writing section as `.text`, else why not.
Every verdict carries the anchor files left out, and why, as `.skipped`:
callers say them, so an anchor never drops out of the prompt unsaid.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Final, Literal

from storyforge.common import DocState, ReferenceDocError, get_plugin_dir, log

VOICE_DIR = os.path.join('reference', 'voice')
BOOK_FILE = os.path.join(VOICE_DIR, 'book.md')
ANCHORS_DIR = os.path.join(VOICE_DIR, 'anchors')
CHECKS_FILE = os.path.join(VOICE_DIR, 'checks.md')
#: the keys an anchor's header may give
ANCHOR_KEYS = ('kind', 'tense', 'pov')
#: the values `scenes.csv`'s `tense` column takes (blank: not said); the
#: schema's enum is this tuple (`schema.COLUMN_SCHEMA['tense']`)
TENSES = ('present', 'past')

#: what makes the voice, named wherever its absence is reported
REMEDY = (f'put at least one passage you chose or finished by hand in {ANCHORS_DIR}/ '
          f'and say what it does in {BOOK_FILE} (references/voice-folder.md; '
          f'`storyforge voice sample --scene <id>`, or `--moment "..."` before the scene '
          f'map, runs blind sample rounds to find one)')

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
    keys, and the passage without the header. `parse_anchor` builds them;
    the constructor holds the same rules (a passage, a tense in `TENSES`)."""
    path: str
    text: str
    kind: tuple[str, ...] = ()
    tense: str = ''
    pov: str = ''

    def __post_init__(self):
        if not self.text.strip():
            raise ValueError(f'{self.path}: the passage is empty')
        if self.tense and self.tense not in TENSES:
            raise ValueError(f'{self.path}: tense {self.tense!r} is not one of '
                             f'{", ".join(TENSES)}')

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


#: `BookVoiceFolder.notes_state`: book.md is the author's text, not there,
#: empty, or still init's template
NOTES_STATES = ('ok', 'missing', 'empty', 'template')


@dataclass(frozen=True)
class BookVoiceFolder:
    """What `reference/voice/` holds for writing: `book.md`'s text ('' unless
    `notes_state` is 'ok'), the anchors in file-name order, and the anchor
    files left out, each with why. checks.md isn't here: it is never read
    for writing (`checks_text`)."""
    notes: str = ''
    notes_state: str = 'missing'
    anchors: tuple[Anchor, ...] = ()
    skipped: tuple[str, ...] = ()


_warned_templates: set[str] = set()


def _template(rel: str) -> str:
    """init's template for a file in the voice folder ('' without one; a
    template `SCAFFOLD` names that can't be read is a WARNING, once: without
    it an unedited copy would pass for the author's text)."""
    path = os.path.join(get_plugin_dir(), 'templates', rel)
    try:
        with open(path, encoding='utf-8-sig') as f:
            return f.read().strip()
    except OSError as e:
        if rel in SCAFFOLD and rel not in _warned_templates:
            _warned_templates.add(rel)
            log(f'WARNING: the plugin\'s template {rel} can\'t be read ({e}): a copy of it in '
                f'a book can\'t be told from the author\'s text')
        return ''


def _same(text: str, template: str) -> bool:
    return text.replace('\r\n', '\n').strip() == template.replace('\r\n', '\n').strip()


def _state(project_dir: str, rel: str) -> tuple[str, str]:
    """(state, text) of a voice file: ('ok', its text), ('missing', ''),
    ('empty', '') or ('template', '').

    Raises:
        ReferenceDocError: the path is there but isn't a file, or can't be read.
    """
    path = os.path.join(project_dir, rel)
    if not os.path.lexists(path):
        return 'missing', ''
    if not os.path.isfile(path):
        raise ReferenceDocError(path, 'not a regular file')
    try:
        with open(path, encoding='utf-8-sig') as f:
            text = f.read().strip()
    except (OSError, UnicodeDecodeError) as e:
        raise ReferenceDocError(path, e) from e
    if not text:
        return 'empty', ''
    template = _template(rel)
    if template and _same(text, template):
        return 'template', ''
    return 'ok', text


def _read(project_dir: str, rel: str) -> str:
    """A voice file's text, stripped: '' when missing, empty or still init's
    template.

    Raises:
        ReferenceDocError: the path is there but isn't a file, or can't be read.
    """
    return _state(project_dir, rel)[1]


_HEADER = re.compile(r'^([A-Za-z_]\w*):\s*(.*)$')


def parse_anchor(rel: str, raw: str) -> Anchor:
    """An anchor from its file's text. The lines before the first blank line
    are a header when every one is `key: value` and at least one key is an
    anchor key (`ANCHOR_KEYS`); otherwise the whole file is the passage.

    Raises:
        ValueError: the header names a key it doesn't take or gives one
            twice, gives a tense that isn't present or past, or has no
            passage after it.
    """
    text = raw.replace('\r\n', '\n').strip()
    head, _sep, body = text.partition('\n\n')
    matches = [_HEADER.match(ln.strip()) for ln in head.split('\n')]
    keys: dict[str, str] = {}
    if all(matches) and any(m.group(1).lower() in ANCHOR_KEYS for m in matches):
        for m in matches:
            key = m.group(1).lower()
            if key not in ANCHOR_KEYS:
                raise ValueError(f'{rel}: the header has `{m.group(1)}:`; it takes '
                                 f'{", ".join(k + ":" for k in ANCHOR_KEYS)}')
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
    """`reference/voice/`'s writing material as it stands (everything empty
    without it). Anchors left out (not a top-level .md file, or one
    `parse_anchor` refuses) are in `skipped`, each with why.

    Raises:
        ReferenceDocError: book.md or an anchor is there but isn't a file or
            can't be read; anchors/ is there but isn't a folder.
    """
    notes_state, notes = _state(project_dir, BOOK_FILE)
    anchors, skipped = [], []
    folder = os.path.join(project_dir, ANCHORS_DIR)
    if os.path.lexists(folder) and not os.path.isdir(folder):
        raise ReferenceDocError(folder, 'not a folder')
    if os.path.isdir(folder):
        try:
            names = sorted(os.listdir(folder))
        except OSError as e:
            raise ReferenceDocError(folder, e) from e
        for name in names:
            path = os.path.join(folder, name)
            rel = os.path.join(ANCHORS_DIR, name)
            if name.startswith('.'):
                continue
            if not name.lower().endswith('.md') or not os.path.isfile(path):
                skipped.append(f'{rel}: not a .md file directly in {ANCHORS_DIR}/, so not read')
                continue
            try:
                with open(path, encoding='utf-8-sig') as f:
                    raw = f.read()
            except (OSError, UnicodeDecodeError) as e:
                raise ReferenceDocError(path, e) from e
            try:
                anchors.append(parse_anchor(rel, raw))
            except ValueError as e:
                skipped.append(str(e))
    return BookVoiceFolder(notes, notes_state, tuple(anchors), tuple(skipped))


def old_voice_files(project_dir: str) -> list[tuple[str, str]]:
    """The pipeline's voice files this book still has, none of which is read
    any more: (path, what it was)."""
    return [(rel, what) for rel, what in OLD_FILES
            if os.path.lexists(os.path.join(project_dir, rel))]


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


def skipped_warning(voice: DocState) -> str:
    """One WARNING line for the anchors a verdict left out ('' for none)."""
    if not voice.skipped:
        return ''
    return (f'WARNING: {len(voice.skipped)} anchor file(s) in {ANCHORS_DIR}/ left out of the '
            f'voice: ' + '; '.join(voice.skipped))


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
    """The book's voice, as one verdict:

    - 'ok': `.text` is the writing section, `.path` the voice folder.
    - 'missing': no book.md and no anchor (`.path` '').
    - 'template' or 'empty': book.md is init's template, or missing or empty
      while anchors are there (`.path` book.md); or book.md is fine and no
      anchor is left (`.path` the anchors folder).
    - 'unreadable': `.path` the file that can't be read (`raise_if_unreadable`).

    Without an author repo the voice needs book.md and an anchor; with one
    (the `voice:` block), the repo's voice is enough. `.skipped` holds the
    anchor files left out, on every verdict.

    Raises:
        voice_repo.VoiceError: a `voice:` block that can't be used.
    """
    from storyforge.voice_repo import author_voice_section, voice_ref
    try:
        folder = read_folder(project_dir)
    except ReferenceDocError as e:
        rel = os.path.relpath(e.path, project_dir) if os.path.isabs(e.path) else e.path
        why = e.__cause__ if e.__cause__ is not None else str(e).rsplit(': ', 1)[-1]
        return DocState('unreadable', rel, f"can't read {rel}: {why}")
    skipped = folder.skipped
    author = author_voice_section(project_dir) if voice_ref(project_dir) else ''
    if author or (folder.notes and folder.anchors):
        return DocState('ok', VOICE_DIR, VOICE_DIR, render(folder, author), skipped)
    if folder.notes_state == 'missing' and not folder.anchors and not skipped:
        return DocState('missing', '', f'{VOICE_DIR}/ has no voice yet', '', skipped)
    if not folder.notes:
        kind = 'template' if folder.notes_state == 'template' else 'empty'
        what = "still init's template" if kind == 'template' else 'missing or empty'
        return DocState(kind, BOOK_FILE, f'{BOOK_FILE} is {what}', '', skipped)
    why = f' ({"; ".join(skipped)})' if skipped else ''
    return DocState('empty', ANCHORS_DIR, f'{ANCHORS_DIR}/ holds no anchor passage{why}', '',
                    skipped)


def checks_text(project_dir: str) -> str:
    """`checks.md`'s text, for a reviewer ('' without one). Never for a
    writing prompt.

    Raises:
        ReferenceDocError: it is there but isn't a file, or can't be read.
    """
    return _read(project_dir, CHECKS_FILE)


# ============================================================================
# Tense (free, code only)
# ============================================================================

#: Common verbs in narration, third person: (present, past). Closed lists of
#: third-person forms: first-person present narration ("I walk") gives
#: almost no present signal, and a homograph (looks, left, rose, saw, felt)
#: is a false one
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
#: speech, which is as people speak: straight, curly and single-curly
#: quotes. A single-curly quote is closed by a ’ not followed by a letter,
#: so "‘I don’t know’" is one quote; a quote left open at a paragraph's end
#: (common in fiction) stops at the line's end
_SPEECH = re.compile(r'"[^"\n]*"|“[^”]*”|‘(?:[^’\n]|’(?=\w))*’')
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
        """The share of the narration's forms in `tense` (one of `TENSES`)."""
        if tense not in TENSES:
            raise ValueError(f'tense {tense!r} is not one of {", ".join(TENSES)}')
        if not self.total:
            return 0.0
        return (self.present if tense == 'present' else self.past) / self.total


def read_tense(prose: str) -> TenseReading:
    """Counts of present and past forms in the narration (speech left out)."""
    narration = _SPEECH.sub(' ', prose)
    words = [w.lower() for w in _WORD.findall(narration)]
    return TenseReading(sum(w in _PRESENT for w in words), sum(w in _PAST for w in words))


#: `TenseCheck.verdict`s
TENSE_OK, TENSE_MISMATCH, TENSE_UNJUDGED, TENSE_NOT_SAID = 'ok', 'mismatch', 'unjudged', 'not said'


@dataclass(frozen=True)
class TenseCheck:
    """The free tense check's verdict on a scene, and what to say."""
    verdict: str
    detail: str = ''


def check_tense(prose: str, declared: str) -> TenseCheck:
    """Whether the narration is in the `declared` tense (scenes.csv's
    `tense`). 'not said': the scene declares none (or a value that isn't a
    tense, said); 'unjudged': under `MIN_TENSE_SIGNALS` verb forms, said so
    the silence isn't read as checked; 'mismatch': `TENSE_MISMATCH_SHARE` or
    more of the forms are the other tense."""
    raw = (declared or '').strip()
    tense = raw.lower()
    if not tense:
        return TenseCheck(TENSE_NOT_SAID)
    if tense not in TENSES:
        return TenseCheck(TENSE_NOT_SAID, f'scenes.csv\'s tense {raw!r} is not one of '
                                          f'{", ".join(TENSES)}, so the tense isn\'t checked')
    reading = read_tense(prose)
    if reading.total < MIN_TENSE_SIGNALS:
        return TenseCheck(TENSE_UNJUDGED, f'the tense isn\'t checked: {reading.total} common '
                                          f'verb form(s) in the narration, under '
                                          f'{MIN_TENSE_SIGNALS}')
    other = 'past' if tense == 'present' else 'present'
    if reading.share(other) >= TENSE_MISMATCH_SHARE:
        return TenseCheck(TENSE_MISMATCH,
                          f'scenes.csv says this scene is told in the {tense} tense, but '
                          f'{reading.share(other):.0%} of the narration\'s common verb forms '
                          f'are {other} ({reading.present} present, {reading.past} past)')
    return TenseCheck(TENSE_OK)


# ============================================================================
# Where the voice stage sits (#656; plan D5 and decision 12)
# ============================================================================

#: the voice is found right after the synopsis and act shape, before the
#: spine and architecture deepen: who tells the story, and from how far,
#: decides which scenes exist and whose eyes they're in (the default)
STAGE_FIRST: Final = 'first'
#: structure first; the voice is found before drafting (the old order), and
#: the check after the map is a NOTE, never the next step
STAGE_LATER: Final = 'later'
VoiceStage = Literal['first', 'later']
STAGE_SETTINGS: tuple[VoiceStage, ...] = (STAGE_FIRST, STAGE_LATER)
#: the line in reference/key-decisions.md that says which (beside
#: `narrator_pov:`); without it, `STAGE_FIRST`
STAGE_KEY = 'voice_stage'
KEY_DECISIONS = os.path.join('reference', 'key-decisions.md')

#: a line that names the key: `voice_stage`, or `voice stage` before a colon
_NAMES_KEY = re.compile(r'voice_stage|voice[ -]stage\W*:', re.I)
#: a setting line once Markdown emphasis, code ticks and quotes are taken
#: out: an optional bullet, the key, a colon, one word, and an optional
#: remark after it in parentheses or after a dash
_SETTING = re.compile(r'^\s*(?:[-*+]\s+)?voice_stage\s*:\s*([A-Za-z]+)\s*'
                      r'(?:[(—–-].*)?$', re.I)
_MARKUP = re.compile(r'[*`"“”‘’]|(?<!\w)\'|\'(?!\w)')


def stage_setting(project_dir: str) -> tuple[VoiceStage, str]:
    """Where the author wants the voice stage: (`STAGE_FIRST` or
    `STAGE_LATER`, a problem to say or ''), from a `voice_stage:` line of
    reference/key-decisions.md. HTML comments are left out, even over
    several lines. A setting line may be a bullet, with bold or code marks
    and quotes around the key or the value (`- **voice_stage:** "later"`),
    in any case, with a remark after it in parentheses. The file is added to
    over time, so the **last** setting line wins; settings that disagree are
    said. No file or no line is `STAGE_FIRST`, the soft default. A line
    naming the key that it can't read, a value it doesn't take, or a file it
    can't read is said, and doesn't change the setting (`STAGE_FIRST` if
    nothing else sets it). Never logged here: `status --json`'s stdout is
    the verdict."""
    path = os.path.join(project_dir, KEY_DECISIONS)
    try:
        with open(path, encoding='utf-8-sig') as f:
            text = f.read()
    except FileNotFoundError:
        return STAGE_FIRST, ''
    except (OSError, UnicodeDecodeError) as e:
        return STAGE_FIRST, (f"{KEY_DECISIONS} can't be read ({e}), so its {STAGE_KEY} isn't "
                             f"known: the voice stage stays first")
    text = re.sub(r'<!--.*?(?:-->|\Z)', '', text, flags=re.S)
    found: list[tuple[VoiceStage, str]] = []   # (value, line)
    problems: list[str] = []
    for line in text.splitlines():
        if not _NAMES_KEY.search(line):
            continue
        m = _SETTING.match(_MARKUP.sub('', line))
        value = m.group(1).lower() if m else ''
        if value == STAGE_FIRST or value == STAGE_LATER:
            found.append((value, line.strip()))
        else:
            problems.append(f'can\'t read {line.strip()!r} (write `{STAGE_KEY}: '
                            f'{STAGE_FIRST}` or `{STAGE_KEY}: {STAGE_LATER}`)')
    setting: VoiceStage = found[-1][0] if found else STAGE_FIRST
    if len({v for v, _ in found}) > 1:
        problems.append(f'its {STAGE_KEY} lines disagree ('
                        + '; '.join(repr(ln) for _, ln in found)
                        + f'): the last one, {setting}, is used')
    if not problems:
        return setting, ''
    return setting, (f'{KEY_DECISIONS}: ' + '; '.join(problems)
                     + f'. The voice stage is {setting}')


#: a word before "narrator" that says there is none ("no narrator", "not a
#: narrator", "without a narrator")
_NO_NARRATOR = re.compile(r'\b(?:no|not|never|nor|without)\b(?:\s+(?:a|an|the|any))?\s*$',
                          re.I)


def _names(text: str, term: str, *, ignore_case: bool = False) -> bool:
    flags = re.I if ignore_case else 0
    return re.search(r'(?<!\w)' + re.escape(term) + r'(?!\w)', text, flags) is not None


def _names_narrator(text: str) -> bool:
    """Whether book.md speaks of a narrator: "narrator" anywhere, any case,
    except where it says there is none ("no narrator")."""
    for m in re.finditer(r'(?<!\w)narrator(?!\w)', text, re.I):
        if not _NO_NARRATOR.search(text[max(0, m.start() - 24):m.start()]):
            return True
    return False


def _character_terms(row: dict[str, str]) -> tuple[set[str], set[str]]:
    """(the words that name a character as written, case and all: their
    name, aliases and id; the words that name them in any case: a
    hyphenated id with spaces). No first names: a first name counts only
    when characters.csv has it as an alias, since one word alone ("Will",
    "Grace", "Hope") is too often an ordinary word."""
    aliases = [a.strip() for a in (row.get('aliases') or '').split(';') if a.strip()]
    ident = (row.get('id') or '').strip()
    exact = {t for t in [(row.get('name') or '').strip(), ident, *aliases] if t}
    loose = {ident.replace('-', ' ')} if '-' in ident else set()
    return exact, loose


def _registry_rows(project_dir: str, name: str) -> list[dict[str, str]]:
    from storyforge.elaborate import _read_csv
    path = os.path.join(project_dir, 'reference', name)
    try:
        return _read_csv(path)
    except (OSError, UnicodeDecodeError) as e:
        raise ReferenceDocError(path, e) from e


def map_povs(project_dir: str) -> list[str]:
    """The POVs of scenes.csv's active scenes, in reading order, each once,
    as written.

    Raises:
        ReferenceDocError: scenes.csv is there but can't be read.
    """
    from storyforge.schema import INACTIVE_STATUSES

    def seq(row):
        try:
            return float(row.get('seq') or 'inf')
        except ValueError:
            return float('inf')

    povs: list[str] = []
    for row in sorted(_registry_rows(project_dir, 'scenes.csv'), key=seq):
        pov = (row.get('pov') or '').strip()
        if pov and (row.get('status') or '').strip() not in INACTIVE_STATUSES \
                and pov not in povs:
            povs.append(pov)
    return povs


def pov_gaps(project_dir: str, notes: str | None = None) -> list[str]:
    """The voice check after the map (#656): the POVs of the map
    (`map_povs`) that book.md says nothing of. A POV is named by its value
    as written, or by the characters.csv name, id or an alias of the
    character it is, as written (case counts: "Grace" names Grace, "grace"
    doesn't), or by a hyphenated id with spaces in any case ("ann lee");
    never by a first name alone unless it's an alias (`_character_terms`). A
    narrator POV (`narrator.is_narrator`) is named when book.md speaks of a
    narrator, not where it says there's none (`_names_narrator`). `notes` is
    book.md's text when the caller has it (default: read it; missing, empty
    or the template is '' and every POV is a gap: with an author repo, the
    book's people still belong in book.md).

    Raises:
        ReferenceDocError: book.md, scenes.csv or characters.csv is there
            but can't be read.
    """
    from storyforge.narrator import is_narrator
    if notes is None:
        notes = _read(project_dir, BOOK_FILE)
    povs = map_povs(project_dir)
    registry: dict[str, tuple[set[str], set[str]]] = {}
    for row in _registry_rows(project_dir, 'characters.csv'):
        terms = _character_terms(row)
        for t in terms[0]:
            registry[t.lower()] = terms
    gaps = []
    for pov in povs:
        if is_narrator(pov, set(registry)):
            covered = _names_narrator(notes)
        else:
            exact, loose = registry.get(pov.lower(), (set(), set()))
            covered = (any(_names(notes, t) for t in exact | {pov})
                       or any(_names(notes, t, ignore_case=True) for t in loose))
        if not covered:
            gaps.append(pov)
    return gaps


# ============================================================================
# Setting up the folder
# ============================================================================

#: the folder's files init and the voice stage copy from templates/
SCAFFOLD = (BOOK_FILE, CHECKS_FILE, os.path.join(ANCHORS_DIR, '.gitkeep'))


def scaffold(project_dir: str, dry_run: bool = False) -> list[str]:
    """Copy the voice folder's missing files from the templates (never over
    a file that's there). Returns what was (or, dry, would be) made,
    relative to the project.

    Raises:
        ReferenceDocError: a folder the layout needs is there as a file.
    """
    for rel in (VOICE_DIR, ANCHORS_DIR):
        path = os.path.join(project_dir, rel)
        if os.path.lexists(path) and not os.path.isdir(path):
            raise ReferenceDocError(path, 'not a folder')
    made = []
    for rel in SCAFFOLD:
        path = os.path.join(project_dir, rel)
        # anchors/.gitkeep only keeps an empty folder in git
        if os.path.lexists(path) or (os.path.basename(rel) == '.gitkeep'
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
    outside it, with no template, or that can't be read, never is)."""
    rel = os.path.normpath(rel)
    if not rel.startswith(VOICE_DIR + os.sep):
        return False
    try:
        return _state(project_dir, rel)[0] == 'template'
    except ReferenceDocError:
        return False
