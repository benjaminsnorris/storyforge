"""Register: a retelling's prose carrying its source translation's old
grammar, idiom and words (#615).

A novel retold from an old translation (Weston's *Gawain*, Butler's or
Lang's Homer) re-voices the source's speeches. A voice guide's banned list
catches archaic *words*; this also catches the translator's *grammar and
idiom* left in modern speech: "bade Gawain take the other", "I'll not",
"fail of my errand", "while my lord is from home", "But that you're Gawain,
I very much doubt".

Two deterministic checks, no API call. Both fold curly apostrophes and
quotes to straight ones before matching; evidence is quoted from the
sentence as written.

- **Patterns** (`PATTERNS`): archaic words (`word`), old grammar such as
  "'ll not" or "it was he." (`syntax`), and old idiom such as "fail of" or
  "have joy of" (`idiom`). Each is narrowed so ordinary modern English
  doesn't match it (`tests/test_register.py` holds a modern corpus that
  must give no findings); a shape that can't be told from modern English,
  such as a fronted verb ("Then came the rain"), isn't checked.
- **Source echo** (`echo`), quoted dialogue only: a run of `ECHO_RUN` or
  more words shared with the source scene the scene adapts (from
  `reference/source-map.csv`), `ECHO_CONTENT` or more of them not common
  function words. A re-voiced line should say the thing in the voice
  guide's words, not the translator's.

Exemptions live in the voice guide, under a heading holding "register
exemptions" (any level, any case), until the next heading of the same or a
higher level. Each bullet is one exemption:

    ## Register exemptions
    - "by my faith", "God keep you" (oaths)
    - "Dust thou art" (liturgy, quoted)
    - scene: brutus-founds-britain-after-troy (the Teller's frame)
    - scenes: `frame-open`; frame-close

A double-quoted phrase (straight or curly quotes) exempts every match inside
an occurrence of it, any case; the words after the quotes are the author's
reason, not read. `scene:`/`scenes:` takes ids split by `,` or `;`, each
item's leading id (backticks allowed), so a reason may follow. A bullet
that can't be used (no double-quoted phrase, a phrase spanning a sentence
break, which can never match because matching is per sentence) and a
`scene:` naming a scene not in `reference/scenes.csv` are WARNINGs, never
silently dropped.

Who uses it:
- `score --register` prints the findings and WARNINGs for the scenes in
  scope; nothing is written. Prose projects only.
- `revision_section`: an adaptation's revision prompt lists the findings
  for the pass's scenes, to check, with the re-voicing rule.
"""

from __future__ import annotations

import csv
import os
import re
from dataclasses import dataclass, field
from typing import Callable, Literal

Kind = Literal['word', 'syntax', 'idiom', 'echo']
KINDS: tuple[str, ...] = ('word', 'syntax', 'idiom', 'echo')

#: (kind, regex, what it is). Matched case-insensitively against one
#: sentence at a time, with curly apostrophes folded to straight; the match
#: is the finding's evidence.
PATTERNS: list[tuple[Kind, str, str]] = [
    # --- words -----------------------------------------------------------
    ('word', r"\b(art thou|thou art|thee|thou|thy|thine|ye|hath|doth|dost|hast)\b",
     'archaic pronoun or verb form'),
    ('word', r"(?<![\w'])('tis|'twas)\b|\b(quoth|methinks|forsooth|prithee|perchance|mayhap|"
             r"verily|betimes|wherefore|whence|whither|hither|thither|anon|ere|nay|yea|wot|"
             r"wist|trow|aught|sooth|fain|liketh|twelvemonth|troth|trouth|bade|befell|befall|"
             r"befallen|befalls|abed|churl|churls|forsook|forswore|mummer|mummers)\b",
     'archaic word'),
    ('word', r"\bhoar\b(?! ?frost)", 'archaic word'),
    # --- grammar ---------------------------------------------------------
    ('syntax', r"\b\w+'(ll|d) not\b", "old negative ('ll not / 'd not)"),
    ('syntax', r"^\W*(then|thus) (spake|quoth|said|answered) (he|she|they|the)\b",
     'fronted "said" ("Then said he")'),
    ('syntax', r"\bbut that (you're|you|he's|he|she's|she|they|it's|it|I'm|I|we)\b",
     '"but that" for "except that"'),
    ('syntax', r"\b(him|those) that (keeps?|holds?|wears?|bears?)\b|^\W*he that \w+",
     '"him that" for "the man who"'),
    ('syntax', r"^\W*(now )?(see|mind|look) you (do|remember|keep|be|go|come|tell)\b",
     'imperative with "you" after the verb'),
    ('syntax', r"\b(ask|tell|give|make|bid) me no more\b", '"ask me no more"'),
    ('syntax', r"\b(give|gave|giving|pay|paid|grant|granted) it (you|me|him|them)\b(?=[.,;!?])",
     'double object without "to"'),
    ('syntax', r"\bbid(s|ding)? (me|him|her|you|them|us) (rise|go|come|take|stay|sit|stand|be|"
               r"do|speak|tell|keep|wait|make)\b",
     '"bid me" for "tell me to"'),
    ('syntax', r"\bas (I|you|he|she) bid\b", '"as I bid"'),
    ('syntax', r"\bthe (less|more) (blame|for it)\b", '"the less blame"'),
    ('syntax', r"\b\w+ you the (less|more)\b(?=[.,;!?]| for\b)", '"I blame you the less"'),
    ('syntax', r"\b(like|love|liked|loved) (you|him|her) well\b", '"I like you well"'),
    ('syntax', r"\b(dead|gone) these\b", '"dead these twenty years"'),
    ('syntax', r"\b(it was|it is|was it) (he|she|they|we)\b(?=[.,;!?])",
     '"it was he" (subject pronoun after "be")'),
    ('syntax', r"\b(stayed|stood|remained|lay|sat) so\b(?=[,.;:!?])",
     '"stayed so" for "stayed like that"'),
    ('syntax', r"\b(be|been|is|was|are|were) (paid|given|granted|sent) (you|him|her|them|me)\b",
     'passive with a bare indirect object ("paid you")'),
    ('syntax', r", nor (better|worse)\b", '"nor" without "neither"'),
    ('syntax', r"\bhold aside\b", '"hold aside your hood"'),
    ('syntax', r"\b(be|was|is) (traitor|coward|recreant)\b",
     'no article before a role ("be traitor")'),
    # --- idiom -----------------------------------------------------------
    ('idiom', r"\b(yes|no), truly\b", '"yes, truly"'),
    ('idiom', r"\bquits(, \w+,)? of\b", '"quits of"'),
    ('idiom', r"\bremarking (it|them)\b", '"remarking it" for "remarking on it"'),
    ('idiom', r"\b(if it|it does|it doesn't|it does not|does it) displeases? (you|me|him|her)\b",
     '"if it doesn\'t displease you"'),
    ('idiom', r"\b(fail|failed|fails) of\b", '"fail of" for "fail in"'),
    ('idiom', r"\bno need of\b|\b(you've|I've|we've|you have|I have|we have) need of\b",
     '"need of" for "need for"'),
    ('idiom', r"\bhave joy of\b", '"have joy of it"'),
    ('idiom', r"\b(lord|lady|master|husband|wife|father|mother|he|she) (is|was|be|being) "
              r"from home\b", '"from home" for "away"'),
    ('idiom', r"\b(?!in\b|of\b|for\b|during\b|over\b|all\b|and\b|but\b)\w+ these (two|three|four|"
              r"five|six|seven|eight|nine|ten|twenty|many) (years|days|weeks|months|winters)\b"
              r"(?! (were|was|have|had|are|is|of|in|since|ago))",
     '"these seven years" for "for seven years"'),
    ('idiom', r"(?<!all )\bthe while\b(?=[,.;!?])", '"the while"'),
    ('idiom', r"\b(think|thinks|thought) on (it|that|this|honou?r)\b", '"think on"'),
    ('idiom', r"\b(done|did) ill\b", '"done ill"'),
    ('idiom', r"\b(seemly|unseemly|in sooth|by my troth)\b", 'old idiom'),
    ('idiom', r"\b(told|tell|tells) over (his|her|their|my) (sins|beads|prayers|tale|losses)\b",
     '"told over his sins"'),
    ('idiom', r"\blaid (it|them) by\b(?=[,.;]| on\b)", '"laid it by"'),
    ('idiom', r"\bhold (yourself|myself|himself|it) (well paid|remedied|paid|excused)\b",
     '"hold yourself well paid"'),
    ('idiom', r"\bfare well\b", '"fare well" as a verb'),
    ('idiom', r"\band have done\b(?=[.!])", '"and have done"'),
    ('idiom', r"\bwrong in me\b|\bill in me\b", '"wrong in me"'),
    ('idiom', r"\b(a fool's|your|my|his|her) asking\b(?! (price|for|about|me|him|her|them|"
              r"us|if|whether|why|how|what|who|where|when|questions?))",
     '"asking" as a noun'),
    ('idiom', r"\bcome what may of it\b|\bwhat may come of it\b", '"come what may of it"'),
]


def _compile(patterns):
    out = []
    for kind, rx, what in patterns:
        assert kind in KINDS and kind != 'echo', f'PATTERNS: bad kind {kind!r}'
        out.append((kind, re.compile(rx, re.IGNORECASE), what))
    return out


_COMPILED = _compile(PATTERNS)

#: the shortest run of words shared with the source that counts as an echo
ECHO_RUN = 5
#: how many of the run's words must not be function words
ECHO_CONTENT = 2
#: words that don't make a shared run distinctive on their own
_FUNCTION_WORDS = frozenset("""
a an the and or but nor so of to in on at by for with from as is was be been are were am
i me my you your he him his she her it its we us our they them their this that these those
not no do did does have has had will would shall should can could may might must there then
than what who whom which when where why how all any some one if into out up down over
""".split())
#: normalizing the translation's forms so "thou art" and "you are" meet
_NORMALIZE = {'thee': 'you', 'thou': 'you', 'ye': 'you', 'thy': 'your', 'thine': 'your',
              'art': 'are', 'hast': 'have', 'hath': 'has', 'doth': 'does', 'dost': 'do',
              'spake': 'spoke', 'naught': 'nothing'}
_CONTRACTIONS = {"can't": ['can', 'not'], "won't": ['will', 'not'], "shan't": ['shall', 'not']}
_SUFFIXES = (("n't", 'not'), ("'ll", 'will'), ("'re", 'are'), ("'ve", 'have'),
             ("'m", 'am'), ("'d", 'would'))
_TOKEN_RE = re.compile(r"[a-z]+(?:'[a-z]+)?")
_SENTENCE_RE = re.compile(r'[^.!?\n]+(?:[.!?]+["”’\']*|\n|$)')
_EXEMPT_HEADING_RE = re.compile(r'^#{1,6}\s+.*register exemptions', re.IGNORECASE)
_QUOTED_RE = re.compile(r'["“]([^"“”]+)["”]')
_SCENE_ITEM_RE = re.compile(r'^`?([A-Za-z0-9][\w-]*)`?')
#: a sentence break inside a phrase: ., ! or ? then a space and more words
_BREAK_RE = re.compile(r'[.!?]["”’\']*\s+\S')


def fold(text: str) -> str:
    """Curly apostrophes and quotes as straight ones, character for
    character, so offsets into the result are offsets into `text`."""
    return (text.replace('’', "'").replace('‘', "'")
            .replace('“', '"').replace('”', '"'))


@dataclass(frozen=True)
class Finding:
    scene_id: str
    kind: Kind
    what: str          # the pattern's name, or the source scene echoed
    evidence: str      # the words as written in the sentence
    sentence: str      # the sentence it is in, as written


@dataclass(frozen=True)
class Exemptions:
    """Phrases (folded and lowercased however they are given), scene ids,
    and the exemption bullets that couldn't be used, each saying why."""
    phrases: tuple[str, ...] = ()
    scenes: frozenset[str] = frozenset()
    problems: tuple[str, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, 'phrases',
                           tuple(fold(p).strip().lower() for p in self.phrases if p.strip()))
        object.__setattr__(self, 'scenes', frozenset(self.scenes))


def read_exemptions(text: str) -> Exemptions:
    """The exemptions under the voice guide's "register exemptions" heading.
    Empty without one. A bullet that can't be used is in `problems`."""
    phrases: list[str] = []
    scenes: set[str] = set()
    problems: list[str] = []
    inside = False
    level = 0
    for line in text.splitlines():
        heading = re.match(r'^(#{1,6})\s', line)
        if heading:
            if _EXEMPT_HEADING_RE.match(line):
                inside, level = True, len(heading.group(1))
                continue
            if inside and len(heading.group(1)) <= level:
                inside = False
        if not inside:
            continue
        item = re.match(r'^\s*[-*]\s+(.*)$', line)
        if not item:
            continue
        body = item.group(1).strip()
        m = re.match(r'^scenes?:\s*(.*)$', body, re.IGNORECASE)
        if m:
            ids = [_SCENE_ITEM_RE.match(part.strip())
                   for part in re.split(r'[,;]', m.group(1)) if part.strip()]
            if not ids or not all(ids):
                problems.append(f'exemption bullet {body!r}: a scene id is missing or '
                                f'unreadable (write `- scene: <id>`)')
            scenes.update(i.group(1) for i in ids if i)
            continue
        quoted = [q.strip() for q in _QUOTED_RE.findall(body) if q.strip()]
        if not quoted:
            problems.append(f'exemption bullet {body!r} has no double-quoted phrase, so it '
                            f'exempts nothing (write `- "the phrase" (why)`)')
            continue
        for q in quoted:
            if _BREAK_RE.search(q):
                problems.append(f'exemption "{q}" spans a sentence break and can never '
                                f'match (matching is per sentence); give each sentence '
                                f'its own quotes')
            else:
                phrases.append(q)
    return Exemptions(tuple(phrases), frozenset(scenes), tuple(problems))


def load_exemptions(project_dir: str) -> Exemptions:
    """`read_exemptions` of reference/voice-guide.md; empty without one. A
    guide that can't be read is a problem, not an exception."""
    path = os.path.join(project_dir, 'reference', 'voice-guide.md')
    try:
        with open(path, encoding='utf-8-sig') as f:
            return read_exemptions(f.read())
    except FileNotFoundError:
        return Exemptions()
    except (OSError, UnicodeDecodeError) as e:
        return Exemptions(problems=(f"reference/voice-guide.md can't be read, so no "
                                    f"register exemptions apply ({e.__class__.__name__}: {e})",))


def _tokens(text: str) -> list[tuple[str, int, int]]:
    """(normalized word, start, end) for each word of `text`: lowercased,
    apostrophes folded, contractions expanded (each part keeping the
    contraction's span) and the translation's forms (`_NORMALIZE`) mapped."""
    out = []
    for m in _TOKEN_RE.finditer(fold(text).lower()):
        tok, s, e = m.group(0), m.start(), m.end()
        parts = _CONTRACTIONS.get(tok)
        if parts is None:
            parts = [tok]
            for suffix, word in _SUFFIXES:
                if tok.endswith(suffix) and len(tok) > len(suffix):
                    parts = [tok[:-len(suffix)], word]
                    break
        out += [(_NORMALIZE.get(p, p), s, e) for p in parts]
    return out


def _normalize(text: str) -> list[str]:
    return [w for w, _, _ in _tokens(text)]


def sentences(text: str) -> list[str]:
    """The sentences of a scene's prose, stripped; a line break ends one."""
    text = text.replace('\r\n', '\n')
    return [s.strip() for s in _SENTENCE_RE.findall(text) if re.search(r'[A-Za-z]', s)]


def _dialogue_sentences(text: str) -> list[str]:
    """The sentences inside quoted speech."""
    from storyforge.prose_analysis import dialogue_spans
    out = []
    for _, _, inner in dialogue_spans(text):
        out += sentences(inner)
    return out


def _exempt(sentence: str, start: int, end: int, phrases: tuple[str, ...]) -> bool:
    low = fold(sentence).lower()
    for p in phrases:
        p = fold(p).lower()
        i = low.find(p)
        while i >= 0:
            if i <= start and end <= i + len(p):
                return True
            i = low.find(p, i + 1)
    return False


def pattern_findings(scene_id: str, text: str,
                     exemptions: Exemptions = Exemptions()) -> list[Finding]:
    """The `PATTERNS` matches in a scene's prose, one per pattern a sentence."""
    if scene_id in exemptions.scenes:
        return []
    out = []
    for sent in sentences(text):
        folded = fold(sent)
        for kind, rx, what in _COMPILED:
            for m in rx.finditer(folded):
                start = m.start()
                while start < m.end() and not (sent[start].isalnum() or sent[start] == "'"
                                               or sent[start] == '’'):
                    start += 1      # a `^\W*` anchor's leading quote isn't evidence
                if not _exempt(sent, start, m.end(), exemptions.phrases):
                    out.append(Finding(scene_id, kind, what, sent[start:m.end()], sent))
                    break
    return out


def _contains(seq: list[str], part: list[str]) -> bool:
    n = len(part)
    return any(seq[i:i + n] == part for i in range(len(seq) - n + 1))


def _ngrams(words: list[str], n: int) -> set[tuple[str, ...]]:
    return {tuple(words[i:i + n]) for i in range(len(words) - n + 1)}


def echo_findings(scene_id: str, text: str, source_texts: dict[str, str],
                  exemptions: Exemptions = Exemptions(), run: int = ECHO_RUN,
                  content: int = ECHO_CONTENT, dialogue_only: bool = True) -> list[Finding]:
    """Sentences sharing a run of `run`+ words with a source scene in
    `source_texts` ({label: prose}), `content`+ of the run's words not
    function words. Each run is the whole stretch of the sentence the
    source shares, in either direction; one finding a sentence, its longest
    run, quoted from the sentence as written."""
    if scene_id in exemptions.scenes or not source_texts:
        return []
    grams: dict[tuple[str, ...], str] = {}
    for label, prose in source_texts.items():
        for g in _ngrams(_normalize(prose), run):
            grams.setdefault(g, label)
    exempt_words = [_normalize(p) for p in exemptions.phrases]
    out = []
    for sent in (_dialogue_sentences(text) if dialogue_only else sentences(text)):
        toks = _tokens(sent)
        words = [w for w, _, _ in toks]
        hits = [tuple(words[i:i + run]) in grams for i in range(len(words) - run + 1)]
        best: tuple[int, int, str] | None = None
        i = 0
        while i < len(hits):
            if not hits[i]:
                i += 1
                continue
            k = i
            while k + 1 < len(hits) and hits[k + 1]:
                k += 1
            start, end = i, k + run          # words[start:end] is the shared run
            span = words[start:end]
            if (sum(w not in _FUNCTION_WORDS for w in span) >= content
                    and not any(_contains(p, span) for p in exempt_words)
                    and (best is None or end - start > best[1] - best[0])):
                best = (start, end, grams[tuple(words[i:i + run])])
            i = k + 1
        if best:
            s, e = toks[best[0]][1], toks[best[1] - 1][2]
            out.append(Finding(scene_id, 'echo', f'shares words with {best[2]}',
                               sent[s:e], sent))
    return out


@dataclass
class SourceTexts:
    """{scene id: {"slug:source id": prose}}, and the mapped scenes whose
    source couldn't be found or has no prose, each with why."""
    texts: dict[str, dict[str, str]] = field(default_factory=dict)
    gaps: dict[str, str] = field(default_factory=dict)


def source_texts_by_scene(project_dir: str) -> SourceTexts:
    """The source prose each mapped scene adapts. A scene the map gives
    source scenes that don't resolve (a typo, a bare id in several sources,
    a source not imported) or have no prose is in `gaps`; an invented scene,
    or one the map gives no source scene, has nothing to compare and is in
    neither. Empty with no `source:` block or no map. Raises
    source.SourceError on a config that can't be read."""
    from storyforge import source
    cfg = source.read_config(project_dir)
    if cfg is None:
        return SourceTexts()
    rows = source.read_source_map(project_dir)
    if not rows:
        return SourceTexts()
    cat = source.catalogue(project_dir, cfg)
    out = SourceTexts()
    for sid, row in source.map_rows_by_scene(rows).items():
        refs = source.split_ids(row.get('source_scenes', ''))
        if not refs or row.get('treatment', '').strip() == 'invent':
            continue
        texts, bad = {}, []
        for ref in refs:
            found = source.resolve_source_id(ref, cat)
            if not found:
                bad.append(f'{ref} (not found in one imported source)')
                continue
            prose = source.source_prose(project_dir, *found)
            if prose:
                texts[f'{found[0]}:{found[1]}'] = prose
            else:
                bad.append(f'{found[0]}:{found[1]} (no source prose)')
        if texts:
            out.texts[sid] = texts
        if bad:
            out.gaps[sid] = 'source scenes not compared: ' + ', '.join(bad)
    return out


@dataclass
class Checked:
    findings: list[Finding]
    unchecked: dict[str, str]     # scene id -> why it has no prose to check (no file)
    echo_note: str                # why the echo check didn't run at all, or ''
    unreadable: dict[str, str] = field(default_factory=dict)   # scene id -> the error
    source_gaps: dict[str, str] = field(default_factory=dict)  # scene id -> echo partly skipped
    exemption_problems: list[str] = field(default_factory=list)

    def warnings(self) -> list[str]:
        """A WARNING line for everything that couldn't be checked or used."""
        out = [f'WARNING: register exemptions: {p}' for p in self.exemption_problems]
        if self.echo_note:
            out.append(f'WARNING: source echo not checked: {self.echo_note}')
        out += [f'WARNING: {sid}: {why}' for sid, why in self.source_gaps.items()]
        out += [f'WARNING: {sid} not checked: {why}' for sid, why in self.unchecked.items()]
        out += [f"WARNING: {sid} not checked: can't be read ({why})"
                for sid, why in self.unreadable.items()]
        return out


def _book_scene_ids(project_dir: str) -> set[str] | None:
    path = os.path.join(project_dir, 'reference', 'scenes.csv')
    try:
        with open(path, encoding='utf-8-sig', newline='') as f:
            return {r.get('id', '').strip() for r in csv.DictReader(f, delimiter='|')} - {''}
    except (OSError, UnicodeDecodeError, csv.Error):
        return None


def check_scenes(scene_ids: list[str], project_dir: str) -> Checked:
    """Both checks over the scenes given, in order."""
    from storyforge import source
    from storyforge.illustrations import read_scene_prose
    exemptions = load_exemptions(project_dir)
    problems = list(exemptions.problems)
    if exemptions.scenes:
        known = _book_scene_ids(project_dir)
        if known is None:
            problems.append("reference/scenes.csv can't be read, so the `scene:` "
                            "exemptions' ids aren't checked")
        else:
            problems += [f'`scene: {s}` names a scene not in reference/scenes.csv'
                         for s in sorted(exemptions.scenes - known)]
    echo_note = ''
    try:
        found = source_texts_by_scene(project_dir)
        if not found.texts and not found.gaps:
            echo_note = ('no source scenes to compare against (no `source:` block, '
                         'no reference/source-map.csv, or no scene mapped to source prose)')
    except (source.SourceError, OSError, UnicodeDecodeError) as e:
        found = SourceTexts()
        echo_note = f"the source can't be read ({e})"
    checked = Checked([], {}, echo_note, exemption_problems=problems)
    for sid in scene_ids:
        if sid in found.gaps:
            checked.source_gaps[sid] = found.gaps[sid]
        path = os.path.join(project_dir, 'scenes', f'{sid}.md')
        if not os.path.isfile(path):
            checked.unchecked[sid] = 'no scene file'
            continue
        try:
            text = read_scene_prose(path)
        except (OSError, UnicodeDecodeError) as e:
            checked.unreadable[sid] = e.__class__.__name__
            continue
        checked.findings += pattern_findings(sid, text, exemptions)
        checked.findings += echo_findings(sid, text, found.texts.get(sid, {}), exemptions)
    return checked


def report_lines(checked: Checked) -> list[str]:
    """`score --register`'s output: two lines per finding (the evidence,
    then its sentence), the counts, then the WARNINGs."""
    from storyforge.common import csv_safe
    lines = []
    for f in checked.findings:
        lines.append(f'{f.scene_id}  {f.kind:<6}  "{csv_safe(f.evidence)}"  ({f.what})')
        lines.append(f'    {csv_safe(f.sentence)}')
    counts: dict[str, int] = {}
    for f in checked.findings:
        counts[f.kind] = counts.get(f.kind, 0) + 1
    scenes = len({f.scene_id for f in checked.findings})
    summary = ', '.join(f'{k} {n}' for k, n in sorted(counts.items())) or 'none'
    lines.append('')
    lines.append(f'Register: {len(checked.findings)} finding(s) in {scenes} scene(s) ({summary})')
    return lines + checked.warnings()


#: the most findings a revision prompt lists (the rest are counted)
REVISION_MAX_FINDINGS = 40


def revision_section(project_dir: str, scene_ids: list[str],
                     warn: Callable[[str], None] | None = None) -> str:
    """The `## Register` section of an adaptation's revision prompt: the
    re-voicing rule and this check's findings in the pass's scenes, for the
    reviser to check. '' with no `source:` block, so other projects' prompts
    are unchanged. What couldn't be checked or used goes to `warn` (the
    log by default). Raises source.SourceError on a `source:` block that
    can't be read."""
    from storyforge import source
    from storyforge.common import log
    from storyforge.prompts_source import REVOICE_RULE
    if source.read_config(project_dir) is None:
        return ''
    warn = warn or log
    checked = check_scenes(scene_ids, project_dir)
    for line in checked.warnings():
        warn(line)
    lines = ['## Register', '', REVOICE_RULE]
    if checked.findings:
        lines += ['', 'The register check flagged these in this pass\'s scenes. Check '
                      'each; change it only if it is archaic or copied from the '
                      'translation (a source echo is the translation\'s own words) and '
                      'the voice guide doesn\'t exempt it:', '']
        for f in checked.findings[:REVISION_MAX_FINDINGS]:
            lines.append(f'- {f.scene_id}: "{f.sentence}" ({f.kind}: {f.evidence}; {f.what})')
        more = len(checked.findings) - REVISION_MAX_FINDINGS
        if more > 0:
            lines.append(f'- ...and {more} more of the same kinds: check those too.')
    return '\n'.join(lines) + '\n'
