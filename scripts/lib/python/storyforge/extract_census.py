"""Extraction's census of named people (#546): who the text names, not only
who is on stage.

The character registry is built from the scene casts, and a cast leaves out
someone named only in a patronymic, an epithet or a genealogy. In a heroic
poem that is how the fathers are named: Beowulf's registry missed Ecgtheow
(16 mentions), Healfdene (18) and Weohstan (9), and Homer names by lineage
throughout ("son of Atreus", "son of Peleus"). Their stories matter to an
adaptation: Ecgtheow's feud is why Beowulf owes Hrothgar.

1. **Count** (code): every capitalized word the scenes use mid-sentence
   (Unicode letters: Hæreth, Zoë, McTavish), with the scenes it is in, less
   the words of the character registry's ids and names, its one-word
   aliases, the head nouns of the location names (not the person in
   "Laertes' Farm"), and the common capitalized words (`_COMMON`). A word
   used only at the start of sentences is not a name.
2. **Ask** (one call per `BATCH` words, the evaluation tier): the words
   used at least `MIN_MENTIONS` times, raised for a long book until at most
   `MAX_ASKED` are left, each with two short passages: which name a person
   (or god, creature, people's founder) and under which id. Peoples,
   places, ships, weapons and the like are not. A word answered on an
   earlier run is not asked again, so a row the author deleted stays
   deleted.
3. **Add**: each person becomes a `characters.csv` row with role
   `referenced`, aliases and pronouns (as the passages use them, else
   empty: #513) from the answer; nothing else is changed. Every
   candidate and answer goes into `working/census.csv`, which is also the
   record of what was answered.
"""

from __future__ import annotations

import csv
import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field

MIN_MENTIONS = 2
# At most this many words are asked about (the Iliad has about 800 candidates)
MAX_ASKED = 300
PASSAGE_WORDS = 14
CENSUS_FILE = os.path.join('working', 'census.csv')

# A word of Unicode letters, hyphens and apostrophes inside it; it counts
# as a name when it starts with a capital and isn't all capitals
_WORD = re.compile(r"[^\W\d_]+(?:[-'’][^\W\d_]+)*")
# Capitalized words that are rarely a person's name, in English prose and in
# the translations the evals use
_COMMON = frozenset('''
I God Lord Heaven Heavens Christ Mary Sir Lady Madam Mr Mrs Miss Dr King Queen Prince
Princess Earl Duke Father Mother Brother Sister Son Sons Daughter Aunt Uncle Captain
Master Mistress The A An And But Or Nor For So Yet Then Now Thus Here There When While
Where Whence Who Whom Whose What Which That This These Those It Its He She They We You
Ye Thou Thee Thy Thine His Her Their Our My Me Him Them Us Oh O Ah Alas Lo Yea Nay Yes
No Not All Each Every Some Any None One Two Three Four Five Six Seven Eight Nine Ten
Monday Tuesday Wednesday Thursday Friday Saturday Sunday January February March April
May June July August September October November December Christmas Easter New Year
Chapter Book Part Fitt Prelude Canto English French Latin Greek Christian Christians
Hence Wherefore Therefore Whither Thither Hither How Why If Unless Till Until After
Before Since Though Although As At By In On Of To From With Without Into Upon Over
Under Let Still Well Ay Aye Fate Fates Death Night Day Morning Dawn Earth Sea Sun Moon
'''.split())


@dataclass
class Candidate:
    word: str
    mentions: int
    scenes: list[str]
    passages: list[str] = field(default_factory=list)


def _location_head(name: str) -> str:
    """A location name without the person it may hold: "Laertes' Farm" ->
    "Farm", "House of Hades" -> "House"."""
    name = re.sub(r"^.*?\b[^\W\d_]+(?:['’]s|s['’]|['’])\s+", '', name.strip())
    return re.split(r"\s+of\s+", name, maxsplit=1)[0]


def _registry_words(ref_dir: str) -> set[str]:
    """The words the registries already account for, lowercased: every word
    of a character's id and name, a one-word alias, and the head of a
    location's name."""
    words: set[str] = set()

    def split(text):
        return {w.lower() for w in re.split(r"[\s\-_'’]+", text) if w}

    for name in ('characters.csv', 'locations.csv'):
        path = os.path.join(ref_dir, name)
        if not os.path.isfile(path):
            continue
        with open(path, newline='', encoding='utf-8') as f:
            for row in csv.DictReader(f, delimiter='|'):
                if name == 'locations.csv':
                    words |= split(_location_head(row.get('name') or ''))
                    continue
                words |= split(' '.join([row.get('id') or '', row.get('name') or '']))
                # An alias counts whole: "ohtere-sons" on Eadgils says
                # nothing about Ohthere himself (B-007)
                for alias in (row.get('aliases') or '').split(';'):
                    alias = alias.strip()
                    if alias and not re.search(r"[\s\-_]", alias):
                        words.add(alias.lower())
    return words


def _sentences_starts(text: str) -> set[int]:
    """Offsets of words that open a sentence, a line or a quotation."""
    starts = {0}
    for m in re.finditer(r'(?:[.!?;:]["\'’”)]*\s+|\n\s*|["“‘(]\s*)', text):
        starts.add(m.end())
    return starts


def count_names(texts: dict[str, str], known: set[str]) -> list[Candidate]:
    """Capitalized words used mid-sentence, not in the registries, most
    mentioned first. A word counts every use (mid-sentence or not) once it
    has at least one mid-sentence use."""
    total: Counter = Counter()
    mid: Counter = Counter()
    where: dict[str, list[str]] = defaultdict(list)
    passages: dict[str, list[str]] = defaultdict(list)
    for sid, text in texts.items():
        text = text.replace('\\\n', '\n')
        starts = _sentences_starts(text)
        for m in _WORD.finditer(text):
            word = re.sub(r"['’]s?$", '', m.group(0))
            if not word[:1].isupper() or word.isupper():
                continue
            if word in _COMMON or word.lower() in known or len(word) < 3:
                continue
            total[word] += 1
            if m.start() not in starts:
                mid[word] += 1
            if sid not in where[word]:
                where[word].append(sid)
            if len(passages[word]) < 2 and (not passages[word] or sid not in passages[word][0]):
                words = text[:m.start()].split()[-PASSAGE_WORDS // 2:] + \
                    text[m.start():].split()[:PASSAGE_WORDS // 2 + 1]
                passages[word].append(f'{sid}: ' + ' '.join(words))
    out = [Candidate(w, n, where[w], passages[w]) for w, n in total.items() if mid[w]]
    out.sort(key=lambda c: (-c.mentions, c.word))
    return out


# ============================================================================
# The call: which candidates are people
# ============================================================================

BATCH = 100


def _schema() -> dict:
    from .extract import _object, _STR, _STR_LIST
    from .schema import VALID_PRONOUNS
    return _object({'names': {'type': 'array', 'items': _object({
        'word': _STR, 'person': {'type': 'boolean'}, 'id': _STR, 'name': _STR,
        'aliases': _STR_LIST,
        'pronouns': {'type': 'string', 'enum': ['', *sorted(VALID_PRONOUNS)]}})}})


CENSUS_SCHEMA = _schema()


def build_census_prompt(candidates: list[Candidate], registry: list[dict[str, str]]) -> str:
    from .schema import VALID_PRONOUNS
    choices = ', '.join(sorted(VALID_PRONOUNS))
    listed = '\n'.join(
        f'- {c.word} ({c.mentions} mentions)\n' + '\n'.join(f'    {p}' for p in c.passages)
        for c in candidates)
    known = '\n'.join(f'- {r["id"]} — {r.get("name", "")}' for r in registry if r.get('id'))
    return f"""These capitalized words appear in a book's text but not in its character registry. Say which of them name a person.

A person here is anyone the text names as an individual: a character on stage or off, a dead father or ancestor named in a lineage ("son of X", "X's son", "the Xing"), a god, a monster or creature with a name, a founder. Not a person: a people, tribe, clan or nation (even one named after a founder), a place, a ship, a sword or other object, a horse unless it acts as a character, an abstraction ("Fate", "Wyrd"), a title or epithet for someone already in the registry ("the Almighty", "the Wielder"), or a common word capitalized at the start of a line.

Judge from the passages only, not from what you know of the work.

## The registry today

{known or '(empty)'}

## The words, each with up to two passages

{listed}

## Answer

`names`: one entry per word above, in order. `word`: the word as given. `person`: true or false. For a person: `id`, a new lowercase-hyphen id from the name as the text spells it (e.g. `ecgtheow`); `name`, the name as the text spells it; `aliases`, other spellings or forms of this one person's name the passages show, never a group ("the sons of X") or another person; `pronouns`, one of {choices} as the passages use them for this person, or empty when they don't show. For a word that is another form of someone already in the registry, `person` is false."""


#: The key of a parsed row holding the model's pronoun answer as given
#: (`parse_census`); `run_census` takes it off before writing the row
ANSWER_KEY = '_pronouns_answer'


def parse_census(reply: str, candidates: list[Candidate], registry_ids: set[str]) -> list[dict]:
    """New registry rows from a census reply: one per person, ids slugged,
    none already in the registry, no group aliases, `pronouns` only as
    `schema.model_pronouns` takes them (the answer as given in
    `ANSWER_KEY`)."""
    from .extract import _json_answer
    from .hone import _slugify, is_group_reference
    from .schema import model_pronouns
    data = _json_answer(reply, CENSUS_SCHEMA)
    words = {c.word for c in candidates}
    rows, seen = [], set(registry_ids)
    for entry in data['names']:
        if not entry.get('person') or str(entry.get('word', '')).strip() not in words:
            continue
        rid = _slugify(str(entry.get('id') or entry.get('word')))
        name = str(entry.get('name') or entry.get('word')).strip()
        if not rid or rid in seen or is_group_reference(name):
            continue
        aliases = [a.strip() for a in entry.get('aliases') or []
                   if a.strip() and a.strip().lower() != name.lower() and not is_group_reference(a)]
        # The passages' pronouns (#513), only as `model_pronouns` takes
        # them; the answer as given is kept in `ANSWER_KEY` for the caller
        # to log and record (it is not a registry column)
        answer = str(entry.get('pronouns') or '').strip()
        pronouns, _ = model_pronouns(answer)
        rows.append({'id': rid, 'name': name, 'role': 'referenced',
                     'aliases': ';'.join(dict.fromkeys(aliases)), 'pronouns': pronouns,
                     ANSWER_KEY: answer})
        seen.add(rid)
    return rows


@dataclass
class CensusResult:
    candidates: int = 0
    asked: int = 0
    added: list[dict] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    #: (name, pronouns) of each person added with pronouns, for the author
    #: to confirm: the model's reading of the passages (#513)
    pronouns_given: list[tuple[str, str]] = field(default_factory=list)
    #: (name, answer) of each pronoun answer that couldn't be used (left empty)
    pronouns_unread: list[tuple[str, str]] = field(default_factory=list)
    note: str = ''
    min_mentions: int = MIN_MENTIONS
    remembered: int = 0       # words answered on an earlier run, not asked again


ANSWERED = ('person', 'not a new person')


def previous_answers(project_dir: str) -> dict[str, str]:
    """The words an earlier census answered (`working/census.csv`): word ->
    answer. A word answered once isn't asked again, so a person the author
    deleted from characters.csv stays deleted."""
    path = os.path.join(project_dir, CENSUS_FILE)
    if not os.path.isfile(path):
        return {}
    with open(path, newline='', encoding='utf-8') as f:
        return {r['word']: r['answer'] for r in csv.DictReader(f, delimiter='|')
                if r.get('word') and r.get('answer') in ANSWERED}


def threshold(found: list[Candidate], least: int = MIN_MENTIONS,
              most: int = MAX_ASKED) -> int:
    """The fewest mentions a word needs to be asked about: *least*, raised
    until at most *most* words are left (a long book's tail of names said
    twice would otherwise fill the asking)."""
    m = least
    while sum(1 for c in found if c.mentions >= m) > most:
        m += 1
    return m


def run_census(project_dir: str, model: str, log_dir: str, on_usage=None,
               min_mentions: int = MIN_MENTIONS) -> CensusResult:
    """Count, ask and add (module docstring). Writes characters.csv (only new
    rows appended) and working/census.csv."""
    from .api import extract_text, invoke_to_file, is_truncated
    from .common import log
    from .elaborate import _read_csv
    from .hone import read_registry, write_registry
    ref_dir = os.path.join(project_dir, 'reference')
    scenes_dir = os.path.join(project_dir, 'scenes')
    rows = [r for r in _read_csv(os.path.join(ref_dir, 'scenes.csv'))
            if (r.get('status') or '').strip() not in ('cut', 'merged')]
    texts = {}
    for r in rows:
        path = os.path.join(scenes_dir, f'{r["id"]}.md')
        if os.path.isfile(path):
            from .illustrations import read_scene_prose
            texts[r['id']] = read_scene_prose(path)
    result = CensusResult()
    if not texts:
        result.note = 'no scene has prose'
        return result
    found = count_names(texts, _registry_words(ref_dir))
    result.candidates = len(found)
    before = previous_answers(project_dir)
    fresh = [c for c in found if c.word not in before]
    result.remembered = len(found) - len(fresh)
    min_mentions = result.min_mentions = threshold(fresh, min_mentions)
    ask = [c for c in fresh if c.mentions >= min_mentions][:MAX_ASKED]
    result.asked = len(ask)
    registry = read_registry(ref_dir, 'characters')
    ids = {r['id'] for r in registry if r.get('id')}
    answered: dict[str, str] = dict(before)
    #: word -> the pronoun answer for the person it names, as given
    said: dict[str, str] = {}
    from .schema import VALID_PRONOUNS
    os.makedirs(log_dir, exist_ok=True)
    for n in range(0, len(ask), BATCH):
        chunk = ask[n:n + BATCH]
        log_file = os.path.join(log_dir, f'extract-census-{n // BATCH + 1}.json')
        try:
            response = invoke_to_file(build_census_prompt(chunk, registry), model, log_file,
                                      8000, label='census', output_schema=CENSUS_SCHEMA)
            if on_usage:
                on_usage(log_file, 'extract-census', 'book', model)
            if is_truncated(response):
                raise ValueError('the reply hit its token limit')
            new = parse_census(extract_text(response), chunk, ids)
        except (RuntimeError, ValueError, OSError) as e:
            log(f'  WARNING: census batch {n // BATCH + 1} failed ({e}); its '
                f'{len(chunk)} word(s) were not checked')
            result.failed += [c.word for c in chunk]
            continue
        for row in new:
            answer = row.pop(ANSWER_KEY, '')
            if row['pronouns']:
                result.pronouns_given.append((row['name'], row['pronouns']))
            elif answer:
                result.pronouns_unread.append((row['name'], answer))
                log(f"  WARNING: census: {row['name']}'s pronouns answer {answer!r} is not one "
                    f"of {', '.join(sorted(VALID_PRONOUNS))}; left empty for the author")
            ids.add(row['id'])
            result.added.append(row)
        for c in chunk:
            row = next((r for r in new if c.word.lower() == r['name'].lower() or any(
                c.word.lower() == a.lower() for a in r['aliases'].split(';'))), None)
            answered[c.word] = 'person' if row else 'not a new person'
            if row:
                said[c.word] = row['pronouns'] or next(
                    (a for n, a in result.pronouns_unread if n == row['name']), '')
    if result.added:
        write_registry(ref_dir, 'characters', registry + result.added)
    path = os.path.join(project_dir, CENSUS_FILE)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f, delimiter='|', lineterminator='\n')
        w.writerow(['word', 'mentions', 'scenes', 'answer', 'pronouns'])
        for c in found:
            answer = (answered.get(c.word) or ('not checked' if c.word in result.failed else
                      f'below {min_mentions} mentions' if c.mentions < min_mentions else
                      'not asked (over the limit)'))
            w.writerow([c.word, c.mentions, len(c.scenes), answer,
                        said.get(c.word, '')])
        # Answers from earlier runs for words now in the registry (or gone
        # from the text) stay on record
        counted = {c.word for c in found}
        for word, answer in before.items():
            if word not in counted:
                w.writerow([word, '', '', answer, ''])
    return result
