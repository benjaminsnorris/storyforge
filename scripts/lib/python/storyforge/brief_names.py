"""Names a rewrite brings in that the book never uses.

Model rewrites of author data (revise's upstream brief fix, hone's brief
passes) can invent people, places or institutions: shared-dark, April 2026,
where upstream brief fixes brought in Mallen, Danny Olinsky, Detective Ruzek
and a prison facility, none of them in the book. ``invented_names`` finds the
capitalized words of a rewrite that the book's own text never uses, so the
caller can reject the rewrite.

``stray_brief_names`` is the same question asked of the briefs already on
disk (#496): names a brief carries that no prose and no reference file uses,
which a draft from that brief would write into the book. ``validate`` reports
it as an advisory finding and ``hone --diagnose`` lists it.
"""

from __future__ import annotations

import os
import re

# A capitalized word: a candidate proper name. Title case only ("Mallen",
# "McKenzie", "Jean-Luc"); all-caps acronyms, accented names and O'Brien-style
# names are not checked.
_NAME_RE = re.compile(r"(?<![\w'’-])([A-Z][a-z][A-Za-z]*(?:[-'’][A-Za-z]+)*)")
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'’-]*")
# After these, or at a field's start, a capitalized word may only open a sentence.
_SENTENCE_START = '.!?:;"\u201c\u2014([|'
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


# The files model rewrites write (revise's upstream brief fix, hone's brief and
# intent passes): neither vouches for a name, since an earlier rewrite may have
# invented it
REWRITTEN_FILES = ('scene-briefs.csv', 'scene-intent.csv')


def reference_text(project_dir: str,
                   exclude: tuple[str, ...] = ('scene-briefs.csv',)) -> str:
    """The reference docs and registries, which make a name the book's own.
    The files model rewrites write (*exclude*) are left out on purpose: names
    an earlier rewrite invented live there."""
    ref_dir = os.path.join(project_dir, 'reference')
    return '\n'.join(
        read_text(os.path.join(ref_dir, name))
        for name in (sorted(os.listdir(ref_dir)) if os.path.isdir(ref_dir) else [])
        if name not in exclude and name.endswith(('.md', '.csv')))


# ============================================================================
# Brief drift: names in the briefs on disk that the book never uses (#496)
# ============================================================================

# The brief fields a draft takes its facts from. knowledge_* and
# physical_state_* hold ledger ids now (lowercase, never a candidate), but an
# older project may still have prose there.
FACT_FIELDS = ('goal', 'conflict', 'outcome', 'crisis', 'decision',
               'key_actions', 'key_dialogue', 'knowledge_in', 'knowledge_out',
               'physical_state_in', 'physical_state_out', 'subtext')

# A run of capitalized words separated by single spaces: "Danny Olinsky",
# "Internal Affairs", "Kedzie Avenue". Reported as one name.
_RUN_RE = re.compile(_NAME_RE.pattern + r"(?: [A-Z][a-z][A-Za-z]*(?:[-'’][A-Za-z]+)*)*")

# Capitalized words a brief uses for ordinary things: titles and kin words
# that come before a name ("Detective Ruzek" is reported because of Ruzek;
# "Detective" alone passes), and the institutional words that make "Internal Affairs" or
# "Police Department" noise rather than a name. Kept short on purpose: a word
# the book uses anywhere, in any case, already passes. Drug and brand names
# still show up; the finding is advisory.
_DRIFT_COMMON = _COMMON_CAPITALIZED | frozenset('''
detective officer sergeant sgt lieutenant lt captain capt chief commander
agent deputy sheriff inspector judge doctor nurse professor father mother
mom dad mama papa aunt uncle grandma grandpa sister brother sir madam
miss lord lady king queen prince princess god
internal affairs department police division unit bureau office court county
city state federal district hospital school university college church
street avenue road station center centre agency council committee
ave blvd rd
'''.split())


def _runs(text: str):
    """(words, opener, possessive) for each capitalized run in *text*:
    possessives stripped; opener when the run opens the field, a sentence
    or a beat; possessive when its first word had one ("Dechlan's")."""
    for m in _RUN_RE.finditer(text or ''):
        raw = m.group(0).split(' ')
        yield ([_strip_possessive(w) for w in raw], _is_opener(text, m.start()),
               _strip_possessive(raw[0]) != raw[0])


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
    Franklins"). The first word of a run that opens the field, a sentence or
    a beat (after ``;``) is usually an ordinary word capitalized there
    ("Consults Tessa"), so it is a candidate only when the briefs use it as
    a name somewhere (*named*: see ``_named``), and it is left out of the
    reported name when it passes."""
    found = []
    for words, opener, _ in _runs(text):
        plain = []
        for i, word in enumerate(words):
            lower = word.lower()
            parts = _name_parts(word)
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


def _book_text(project_dir: str) -> tuple[str, set[str]]:
    """All scene prose (``scenes/*.md``, and a graphic novel's ``pages/*.md``)
    and the ids of the scenes that have some."""
    texts, drafted = [], set()
    for sub in ('scenes', 'pages'):
        folder = os.path.join(project_dir, sub)
        if not os.path.isdir(folder):
            continue
        for name in sorted(os.listdir(folder)):
            if not name.endswith('.md'):
                continue
            text = read_text(os.path.join(folder, name))
            texts.append(text)
            if sub == 'scenes' and text.strip():
                drafted.add(name[:-3])
    return '\n'.join(texts), drafted


def stray_brief_names(project_dir: str, briefs_map: dict[str, dict[str, str]],
                      scene_ids=None) -> dict[str, dict[str, list[str]]]:
    """Names in the briefs' ``FACT_FIELDS`` that appear nowhere in the book:
    scene id -> field -> names, for the scenes (in *scene_ids*, or all) with
    any. Deterministic, no model calls.

    A name passes when the book's prose (every scene's, not only its own) or
    a reference file but ``REWRITTEN_FILES`` uses the word, in any case:
    characters.csv and locations.csv names and aliases, the other registries,
    the bibles. The briefs and intent don't vouch for a drafted scene's
    names, since a rewrite that drifted wrote them (shared-dark's ac569274
    put Olinsky and Ruzek in many briefs at once). A scene with no prose yet
    is also compared against the other scenes' briefs: in a book still being
    planned, a name the briefs share is the plan, and one brief alone naming
    someone no registry knows is the signal.

    A word opening a field, sentence or beat counts only when the briefs
    also use it as a name somewhere (capitalized mid-sentence, or possessive),
    so "Consults Tessa" isn't a name but "Olinsky arrives" is when another
    brief says "with Olinsky" or "Olinsky's car".

    Over-reports a little: drug and brand names, and words capitalized for
    emphasis that the book never uses. Misses a name that only ever opens a
    sentence or beat, and a known name given a new role."""
    book, drafted = _book_text(project_dir)
    base = _known_words('\n'.join((book, reference_text(project_dir, exclude=REWRITTEN_FILES))))
    named = _named(row.get(f, '') or '' for row in briefs_map.values() for f in FACT_FIELDS)

    brief_words = {sid: _known_words('\n'.join(row.get(f, '') or '' for f in FACT_FIELDS))
                   for sid, row in briefs_map.items()}
    in_briefs: dict[str, int] = {}
    for words in brief_words.values():
        for w in words:
            in_briefs[w] = in_briefs.get(w, 0) + 1

    wanted = set(scene_ids) if scene_ids is not None else None
    result: dict[str, dict[str, list[str]]] = {}
    for sid, row in briefs_map.items():
        if wanted is not None and sid not in wanted:
            continue
        known = base
        if sid not in drafted:
            own = brief_words[sid]
            known = base | {w for w, n in in_briefs.items() if n - (w in own) > 0}
        by_field = {}
        for field in FACT_FIELDS:
            names = list(dict.fromkeys(_stray_runs(row.get(field, '') or '', known, named)))
            if names:
                by_field[field] = names
        if by_field:
            result[sid] = by_field
    return result


def describe_strays(by_field: dict[str, list[str]]) -> str:
    """``goal: Olinsky; key_actions: Detective Ruzek, Kedzie`` — one line,
    safe for a pipe-delimited report (the names are the author's text)."""
    from storyforge.common import csv_safe
    return csv_safe('; '.join(f'{field}: {", ".join(names)}'
                              for field, names in by_field.items()))
