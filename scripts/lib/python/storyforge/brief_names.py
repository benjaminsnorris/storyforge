"""Names a rewrite brings in that the book never uses.

Model rewrites of author data (revise's upstream brief fix, hone's brief
passes) can invent people, places or institutions: shared-dark, April 2026,
where upstream brief fixes brought in Mallen, Danny Olinsky, Detective Ruzek
and a prison facility, none of them in the book. ``invented_names`` finds the
capitalized words of a rewrite that the book's own text never uses, so the
caller can reject the rewrite.
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
_SENTENCE_START = '.!?:;"\u201c\u2014(|'
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
    known: set[str] = set()
    for token in _WORD_RE.findall(known_text):
        token = _strip_possessive(token)
        known.add(token.lower())
        known.update(_name_parts(token))
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
            before = text[:m.start()].rstrip()
            opener = not before or before[-1] in _SENTENCE_START
            if opener and _stem(lower) in stems:
                continue
            found.add(name)
    return sorted(found)


def read_text(path: str) -> str:
    with open(path, encoding='utf-8', errors='replace') as f:
        return f.read()


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
