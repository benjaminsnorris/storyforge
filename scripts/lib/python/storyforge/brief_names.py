"""Names a rewrite brings in that the book never uses.

Model rewrites of author data (revise's upstream brief fix, hone's brief
passes) can invent people, places or institutions: shared-dark, April 2026,
where upstream brief fixes brought in Mallen, Danny Olinsky, Detective Ruzek
and a prison facility, none of them in the book. ``invented_names`` finds the
capitalized words of a rewrite that the book's own text never uses, so the
caller can reject the rewrite.

``brief_drift`` is the same question asked of the briefs already on disk
(#496): names a brief carries that no prose and no reference file uses,
which a draft from that brief would write into the book. ``validate``
reports it as an advisory finding and ``hone --diagnose`` lists it.
"""

from __future__ import annotations

import os
import re
from typing import NamedTuple

# A capitalized word: a candidate proper name. Title case only ("Mallen",
# "McKenzie", "Jean-Luc"); all-caps acronyms, accented names and O'Brien-style
# names are not checked.
_NAME_RE = re.compile(r"(?<![\w'’-])([A-Z][a-z][A-Za-z]*(?:[-'’][A-Za-z]+)*)")
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'’-]*")
# After these, or at a field's start, a capitalized word may only open a sentence.
_SENTENCE_START = '.!?:;"“—(|'
# Capitalized words no book invents: calendar words, titles, and sentence
# openers a short reference set might not contain.
_COMMON_CAPITALIZED = frozenset('''
monday tuesday wednesday thursday friday saturday sunday january february
march april may june july august september october november december
mr mrs ms dr st he she it we they you his her its their our your this that
these those there then when while if as at in on of to for from with by
after before but and or so not no yes the an
'''.split())


def _strip_possessive(word: str) -> str:
    return re.sub(r"['’]s$", '', word)


def _name_parts(word: str) -> list[str]:
    """``Jean-Luc`` -> jean, luc; ``McKenzie`` -> mc, kenzie."""
    return [p.lower() for p in re.findall(r'[A-Z]?[a-z]+', word)]


def _stem(word: str) -> str:
    for suffix in ('ing', 'ed', 'es', 'e', 's', 'ly'):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[:-len(suffix)]
    return word


def _known_words(known_text: str) -> set[str]:
    """Every word of *known_text*, lowercased and without a possessive, plus
    the parts of hyphenated and camel-case names."""
    known: set[str] = set()
    for token in _WORD_RE.findall(known_text):
        token = _strip_possessive(token)
        known.add(token.lower())
        known.update(_name_parts(token))
    return known


def _is_opener(text: str, start: int) -> bool:
    before = text[:start].rstrip()
    return not before or before[-1] in _SENTENCE_START


def invented_names(fields: list[str], known_text: str) -> list[str]:
    """Capitalized words in ``fields`` that ``known_text`` never uses, in any
    case. A word that opens a field or a sentence is checked too, but also
    passes when the known text uses another form of it ("Refuses" against
    "refused"), since it may be an ordinary word. Used to reject brief
    rewrites that bring in people, places or institutions (shared-dark, April
    2026: upstream brief fixes brought in Mallen, Danny Olinsky, Detective
    Ruzek and a prison facility, none of them in the book). It cannot catch
    a known name given a new role (the book's Hank Voigt recast as a police
    sergeant)."""
    known = _known_words(known_text)
    stems = {_stem(w) for w in known}
    found = set()
    for text in fields:
        for m in _NAME_RE.finditer(text or ''):
            name = _strip_possessive(m.group(1))
            lower = name.lower()
            if lower in known or lower in _COMMON_CAPITALIZED:
                continue
            parts = _name_parts(name)
            if len(parts) > 1 and all(p in known for p in parts):
                continue
            if _is_opener(text, m.start()) and _stem(lower) in stems:
                continue
            found.add(name)
    return sorted(found)


def read_text(path: str) -> str:
    with open(path, encoding='utf-8', errors='replace') as f:
        return f.read()


def read_text_noting(path: str, notes: list[str], label: str) -> str:
    """*path*'s text, or '' with a note when it can't be read. A file that
    isn't UTF-8 is read with replacement characters, and noted."""
    try:
        with open(path, 'rb') as f:
            data = f.read()
    except OSError as e:
        notes.append(f'{label} could not be read ({e.strerror or e}): not used')
        return ''
    try:
        return data.decode('utf-8-sig')
    except UnicodeDecodeError:
        notes.append(f'{label} is not UTF-8: read with replacement characters')
        return data.decode('utf-8', errors='replace')


# The files model rewrites write (revise's upstream brief fix, hone's brief and
# intent passes): neither vouches for a name, since an earlier rewrite may have
# invented it. reference_text leaves both out by default.
REWRITTEN_FILES = ('scene-briefs.csv', 'scene-intent.csv')

# The reference formats read as text. Images and PDFs (a graphic novel's
# canon art) are skipped as holding no text to read; anything else is
# skipped too, and a caller that passes *notes* is told which
_TEXT_EXTENSIONS = ('.md', '.csv', '.txt', '.yaml', '.yml', '.json')
_NO_TEXT_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.pdf')


def reference_text(project_dir: str, exclude: tuple[str, ...] = REWRITTEN_FILES,
                   notes: list[str] | None = None) -> str:
    """The reference docs and registries, which make a name the book's own:
    every text file under reference/, subfolders included (canon/, an
    adaptation's source/<slug>/). The files model rewrites write (*exclude*,
    at the top level of reference/) are left out on purpose: names an
    earlier rewrite invented live there.

    Without *notes* an unreadable file raises, as it always did. With
    *notes*, it is skipped and noted (as are non-UTF-8 files and files in a
    format that isn't text, images and PDFs aside), so the caller can say
    what it didn't read."""
    ref_dir = os.path.join(project_dir, 'reference')
    texts, skipped = [], []
    for root, dirs, files in os.walk(ref_dir):
        dirs[:] = sorted(d for d in dirs if not d.startswith('.'))
        for name in sorted(files):
            if name.startswith('.') or (root == ref_dir and name in exclude):
                continue
            if not name.lower().endswith(_TEXT_EXTENSIONS):
                if not name.lower().endswith(_NO_TEXT_EXTENSIONS):
                    skipped.append(os.path.relpath(os.path.join(root, name), project_dir))
                continue
            path = os.path.join(root, name)
            texts.append(read_text(path) if notes is None else
                         read_text_noting(path, notes, os.path.relpath(path, project_dir)))
    if notes is not None and skipped:
        notes.append(f"not a text format, not read: {', '.join(skipped)}")
    return '\n'.join(texts)


# ============================================================================
# Brief drift: names in the briefs on disk that the book never uses (#496)
# ============================================================================
#
# Its own word rules, not invented_names': that guard judges a model's new
# text and rejects the rewrite, so it is strict (every capitalized word,
# sentence openers too, a minimal common-word list). This check reads text
# an author may have written and only reports, over a whole book, so it is
# lenient: multi-word runs, titles and institutional words, abbreviations
# that don't end a sentence, Unicode names. Changing it never changes what
# the guard rejects.

# The brief fields a draft takes its facts from (all scene-briefs columns,
# elaborate._BRIEFS_COLS). knowledge_* and physical_state_* hold ledger ids
# now (lowercase, never a candidate), but an older project may still have
# prose there.
FACT_FIELDS = ('goal', 'conflict', 'outcome', 'crisis', 'decision',
               'key_actions', 'key_dialogue', 'knowledge_in', 'knowledge_out',
               'physical_state_in', 'physical_state_out', 'subtext')

# A word: Unicode letters, joined by an apostrophe or hyphen (Zoë, José,
# O'Brien, Jean-Luc, Olinsky's)
_D_WORD = r"[^\W\d_]+(?:['’-][^\W\d_]+)*"
_D_WORD_RE = re.compile(_D_WORD)
# Words separated by single spaces; _runs keeps the capitalized ones
_D_RUN_RE = re.compile(rf"(?<![\w'’-]){_D_WORD}(?: {_D_WORD})*")
# After these, or at a field's start, a word opens a sentence, a beat (key
# actions are ;-separated) or a bracketed note ("[Minimal dialogue]")
_D_OPENERS = _SENTENCE_START + '['
# A period after one of these ends an abbreviation, not a sentence
# ("Tessa sees Dr. Kossuth")
_ABBREVIATIONS = frozenset('''
mr mrs ms mx dr st sgt det lt capt cpt col gen maj cmdr prof rev fr sr jr
insp supt cpl pvt adm gov sen rep hon mt ft
'''.split())

# Capitalized words a brief uses for ordinary things: titles and kin words
# that come before a name ("Detective Ruzek" is reported because of Ruzek;
# "Detective" alone passes), and the institutional words that make
# "Internal Affairs" or "Police Department" noise rather than a name. More
# lenient than the guard's _COMMON_CAPITALIZED on purpose (see above). Kept
# short: a word the book uses anywhere, in any case, already passes. Drug
# and brand names still show up; the finding is advisory. The question words
# are here because a contraction ("Who's there?") reads as a possessive, and
# the pronoun I's contractions because they are capitalized mid-sentence
# ("Gawain: I'm the weakest") like a name (G-022).
_DRIFT_COMMON = _COMMON_CAPITALIZED | _ABBREVIATIONS | frozenset('''
detective officer sergeant lieutenant captain chief commander
agent deputy sheriff inspector judge doctor nurse professor father mother
mom dad mama papa aunt uncle grandma grandpa sister brother sir madam
miss lord lady king queen prince princess god
internal affairs department police division unit bureau office court county
city state federal district hospital school university college church
street avenue road station center centre agency council committee
ave blvd rd
who what where why how here let
i'm i've i'll i'd i’m i’ve i’ll i’d
'''.split())


def _capitalized(word: str) -> bool:
    """An upper-case first letter and a lower-case letter somewhere: Zoë,
    O'Brien, McKenzie; not FBI."""
    return word[0].isupper() and any(c.islower() for c in word)


def _d_strip_possessive(word: str) -> str:
    return re.sub(r"['’]s$", '', word)


def _d_parts(word: str) -> list[str]:
    """``Jean-Luc`` -> jean, luc; ``McKenzie`` -> mc, kenzie; Unicode-aware."""
    parts = []
    for piece in re.split(r"['’-]", word):
        current = ''
        for c in piece:
            if c.isupper() and current:
                parts.append(current.lower())
                current = ''
            current += c
        if current:
            parts.append(current.lower())
    return parts


def _d_known_words(text: str) -> set[str]:
    known: set[str] = set()
    for token in _D_WORD_RE.findall(text):
        token = _d_strip_possessive(token)
        known.add(token.lower())
        known.update(_d_parts(token))
    return known


def _d_is_opener(text: str, start: int) -> bool:
    before = text[:start].rstrip()
    if not before:
        return True
    if before[-1] == '.':
        m = re.search(r'([^\W\d_]+)\.$', before)
        if m and m.group(1).lower() in _ABBREVIATIONS:
            return False
    return before[-1] in _D_OPENERS


def _runs(text: str):
    """(words, opener, possessive) for each run of capitalized words in
    *text*: possessives stripped; opener when the run opens the field, a
    sentence, a beat or a bracketed note; possessive when its first word had
    one ("Dechlan's")."""
    for m in _D_RUN_RE.finditer(text or ''):
        pos = m.start()
        run: list[str] = []
        run_start = pos
        for word in m.group(0).split(' ') + ['']:
            if word and _capitalized(word):
                if not run:
                    run_start = pos
                run.append(word)
            elif run:
                yield ([_d_strip_possessive(w) for w in run], _d_is_opener(text, run_start),
                       _d_strip_possessive(run[0]) != run[0])
                run = []
            pos += len(word) + 1


def _named(texts) -> set[str]:
    """The words *texts* use the way only a name is used: capitalized
    mid-sentence, or possessive where a sentence or beat opens ("Dechlan's
    riders"; a verb opening a beat never takes 's). Lowercased."""
    named = set()
    for text in texts:
        for words, opener, possessive in _runs(text):
            named.update(w.lower() for w in (words[1:] if opener and not possessive else words))
    return named


def _stray_runs(text: str, known: set[str], named: set[str]) -> list[str]:
    """The capitalized runs in *text* with a word *known* doesn't vouch for.
    A plural or singular the book uses passes ("Franklin" for "the
    Franklins"). Only the first word of a run that opens the field, a
    sentence, a beat (after ``;``) or a bracketed note is excused: it is
    usually an ordinary word capitalized there ("Consults Tessa"), so it is
    a candidate only when some brief uses that word as a name (*named*, see
    ``_named``), and it is left out of the reported name when it passes."""
    found = []
    for words, opener, _ in _runs(text):
        plain = []
        for i, word in enumerate(words):
            lower = word.lower()
            parts = _d_parts(word)
            plain.append(lower in known or lower in _DRIFT_COMMON
                         or lower + 's' in known or (lower[-1] == 's' and lower[:-1] in known)
                         or (len(parts) > 1 and all(p in known for p in parts))
                         or (i == 0 and opener and lower not in named))
        if all(plain):
            continue
        if opener and plain[0]:
            words = words[1:]
        found.append(' '.join(words))
    return found


def _page_scenes(text: str, filename: str, scene_ids) -> list[str]:
    """The scenes a graphic novel's page file belongs to: its frontmatter
    `scene_id`, else every scene whose page prefix is the file's
    (``pages.page_id_prefix_for_scene``, as ``pages.pages_for_scene``)."""
    from storyforge.pages import page_id_prefix_for_scene
    m = re.search(r'^scene_id:\s*(\S+)\s*$', text, re.MULTILINE)
    if m:
        return [m.group(1).strip('\'"')]
    prefix = re.sub(r'-p\d+\.md$', '', filename)
    return [sid for sid in scene_ids if page_id_prefix_for_scene(sid) == prefix]


def _page_body(text: str) -> str:
    from storyforge.pages import FRONTMATTER_RE
    m = FRONTMATTER_RE.match(text)
    return m.group(2) if m else text


def _book_text(project_dir: str, scene_ids, notes: list[str]) -> tuple[str, set[str]]:
    """All scene prose (``scenes/*.md``, and a graphic novel's
    ``pages/*.md``) and the ids of the scenes that have some: a scene file
    that isn't blank, or a page file whose body isn't blank."""
    texts, drafted = [], set()
    for sub in ('scenes', 'pages'):
        folder = os.path.join(project_dir, sub)
        if not os.path.isdir(folder):
            continue
        for name in sorted(os.listdir(folder)):
            if not name.endswith('.md') or name.startswith('.'):
                continue
            path, label = os.path.join(folder, name), f'{sub}/{name}'
            if sub == 'scenes':   # a marker id is not a name the book uses (#280)
                from storyforge.illustrations import read_scene_prose
                text = read_scene_prose(path, notes=notes, label=label)
            else:
                text = read_text_noting(path, notes, label)
            text = text.replace('\r\n', '\n')
            texts.append(text)
            if sub == 'scenes' and text.strip():
                drafted.add(name[:-3])
            elif sub == 'pages' and _page_body(text).strip():
                drafted.update(_page_scenes(text, name, scene_ids))
    return '\n'.join(texts), drafted


class DriftReport(NamedTuple):
    """``strays``: scene id -> field -> names. ``checked``: how many briefs
    were checked (a selected row with a fact field filled). ``undrafted``:
    how many of those have no prose yet. ``notes``: what couldn't be
    checked or read, each a sentence for the caller to report: a result
    with notes is incomplete, not clean."""
    strays: dict[str, dict[str, list[str]]]
    checked: int
    undrafted: int
    notes: list[str]


def _read_briefs(path: str, notes: list[str]) -> tuple[list[str], list[dict[str, str]]]:
    """The briefs file's header and rows, BOM and CRLF stripped (as
    ``elaborate._read_csv``); a note when it can't be read."""
    import csv
    from storyforge.elaborate import DELIMITER
    text = read_text_noting(path, notes, 'reference/scene-briefs.csv')
    lines = text.replace('\r\n', '\n').replace('\r', '').splitlines()
    if not lines:
        return [], []
    header = [h.strip() for h in lines[0].split(DELIMITER)]
    rows = [{k: (v or '') for k, v in r.items() if k is not None}
            for r in csv.DictReader(lines, delimiter=DELIMITER)]
    return header, rows


def brief_drift(project_dir: str, scene_ids=None) -> DriftReport:
    """Names in the briefs' ``FACT_FIELDS`` that appear nowhere in the book,
    for the scenes in *scene_ids* (or all). Deterministic, no model calls.

    A name passes when any scene's prose (every scene's, not only its own;
    a graphic novel's pages too) or a reference file but ``REWRITTEN_FILES``
    uses the word, in any case: characters.csv and locations.csv names and
    aliases, the other registries, the bibles, canon/ and source/.

    The briefs never vouch for each other, drafted or not. A rewrite that
    drifted puts its names in several briefs at once (shared-dark's put
    Olinsky in many), so briefs that vouched for each other would hide it,
    and keep a stray alive after the author fixed one of them. A planned
    name that is real belongs in characters.csv or locations.csv (or an
    alias), where the drafting prompt reads it too; the check then passes it.

    Over-reports a little: drug and brand names, and words capitalized for
    emphasis that the book never uses. Misses a name that only ever opens a
    sentence or beat, and a known name given a new role."""
    notes: list[str] = []
    path = os.path.join(project_dir, 'reference', 'scene-briefs.csv')
    if not os.path.isfile(path):
        return DriftReport({}, 0, 0, ['No reference/scene-briefs.csv: no briefs to check'])
    header, rows = _read_briefs(path, notes)
    if 'id' not in header:
        notes.append("reference/scene-briefs.csv has no pipe-delimited 'id' column: "
                     "briefs not checked")
        return DriftReport({}, 0, 0, notes)
    fields = [f for f in FACT_FIELDS if f in header]
    missing = [f for f in FACT_FIELDS if f not in header]
    if missing:
        notes.append(f"reference/scene-briefs.csv has no {', '.join(missing)} column(s): "
                     f"not checked")
    all_ids = [r['id'].strip() for r in rows if r.get('id', '').strip()]
    briefs = {r['id'].strip(): r for r in rows if r.get('id', '').strip()}
    if scene_ids is not None:
        wanted = list(dict.fromkeys(scene_ids))
        absent = [sid for sid in wanted if sid not in briefs]
        if not wanted:
            notes.append('No scenes selected: no briefs checked')
        elif absent:
            notes.append(f"No brief row for {', '.join(absent)}: not checked")
        briefs = {sid: briefs[sid] for sid in wanted if sid in briefs}
    empty = [sid for sid, r in briefs.items()
             if not any((r.get(f) or '').strip() for f in fields)]
    if empty:
        notes.append(f"{len(empty)} brief(s) with every fact field empty, not checked: "
                     f"{', '.join(sorted(empty))}")

    book, drafted = _book_text(project_dir, all_ids, notes)
    known = _d_known_words('\n'.join((book, reference_text(
        project_dir, exclude=REWRITTEN_FILES, notes=notes))))
    named = _named((r.get(f) or '') for r in rows for f in fields)

    strays: dict[str, dict[str, list[str]]] = {}
    checked = undrafted = 0
    for sid, row in briefs.items():
        if sid in empty:
            continue
        checked += 1
        undrafted += sid not in drafted
        by_field = {}
        for field in fields:
            names = list(dict.fromkeys(_stray_runs(row.get(field) or '', known, named)))
            if names:
                by_field[field] = names
        if by_field:
            strays[sid] = by_field
    return DriftReport(strays, checked, undrafted, notes)


def checked_scope(report: DriftReport) -> str:
    """What a result covers: ``12 brief(s) (3 with no prose yet) checked
    against all scene prose and the reference files ...``."""
    extra = f' ({report.undrafted} with no prose yet)' if report.undrafted else ''
    return (f'{report.checked} brief(s){extra} checked against all scene prose and the '
            f'reference files (scene-briefs.csv and scene-intent.csv not counted)')


def describe_strays(by_field: dict[str, list[str]]) -> str:
    """``goal: Olinsky; key_actions: Detective Ruzek, Kedzie`` — one line,
    safe for a pipe-delimited report (the names are the author's text)."""
    from storyforge.common import csv_safe
    return csv_safe('; '.join(f'{field}: {", ".join(names)}'
                              for field, names in by_field.items()))
