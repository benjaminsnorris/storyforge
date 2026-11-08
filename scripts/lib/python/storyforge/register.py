"""Register: a retelling's prose carrying its source translation's old
grammar, idiom and words (#615).

A novel retold from an old translation (Weston's *Gawain*, Butler's or
Lang's Homer) re-voices the source's speeches. A voice guide's banned list
catches archaic *words*; this also catches the translator's *grammar and
idiom* left in modern speech: "bade Gawain take the other", "I'll not",
"fail of my errand", "while my lord is from home", "Then came hooves on the
flags", "But that you're Gawain, I very much doubt".

Two deterministic checks, no API call:

- **Patterns** (`PATTERNS`): archaic words (`word`), old grammar such as
  "'ll not" or a fronted verb (`syntax`), and old idiom such as "fail of" or
  "these seven years" (`idiom`).
- **Source echo** (`echo`): a run of `ECHO_RUN` or more words shared with the
  source scene the scene adapts (from `reference/source-map.csv`), holding
  at least one word that isn't a common function word. A re-voiced line
  should say the thing in the voice guide's words, not the translator's.

Exemptions live in the voice guide, under a heading holding "register
exemptions" (any level, any case). Each bullet is one exemption:

    ## Register exemptions
    - "by my faith", "God keep you" (oaths)
    - "Dust thou art" (liturgy, quoted)
    - scene: brutus-founds-britain-after-troy (the Teller's frame)

A quoted phrase exempts every match inside an occurrence of it (any case);
`scene: <id>[, <id>...]` exempts whole scenes. The words after the quotes
are the author's reason, not read.

`score --register` prints the findings for the scenes in scope; nothing is
written. Prose projects only.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

#: (kind, regex, what it is). Matched case-insensitively against one
#: sentence at a time; the match is the finding's evidence.
PATTERNS: list[tuple[str, str, str]] = [
    # --- words -----------------------------------------------------------
    ('word', r"\b(art thou|thou art|thee|thou|thy|thine|ye|hath|doth|dost|hast)\b",
     'archaic pronoun or verb form'),
    ('word', r"\b(quoth|methinks|forsooth|prithee|perchance|mayhap|verily|betimes|"
             r"wherefore|whence|whither|hither|thither|anon|ere|nay|yea|wot|wist|"
             r"trow|naught|nought|aught|sooth|fain|beseech|liketh|'tis|'twas|"
             r"twelvemonth|troth|trouth|bade|befell|befall|befallen|befalls|"
             r"abed|churl|churls|hoar|whilst|forsook|forswore|mummer|mummers)\b",
     'archaic word'),
    # --- grammar ---------------------------------------------------------
    ('syntax', r"\b\w+'(ll|d) not\b", "old negative ('ll not / 'd not)"),
    ('syntax', r"^\W*(then|there|thus|now|so|here|up|down|in|out) (came|comes|went|rode|stood|"
               r"sat|lay|rose|fell|ran|spoke|spake|answered)\b(?! (back|out|up|down|in|to)\b)",
     'fronted verb (inversion)'),
    ('syntax', r"\bbut that (you're|you|he's|he|she's|she|they|it's|it|I'm|I|we)\b",
     '"but that" for "except that"'),
    ('syntax', r"\b(him|he|her|them|they|those) that (keeps?|holds?|has|had|is|was|"
               r"wears?|bears?|comes?|came|would|will|can|could)\b",
     '"him that" for "the man who"'),
    ('syntax', r"\b(see|mind|look) you (do|don't|remember|keep|be|go|come|tell)\b",
     'imperative with "you" after the verb'),
    ('syntax', r"\b(ask|tell|give|make|bid) me no more\b", '"ask me no more"'),
    ('syntax', r"\bwhether (he|she|they|I|you|we) would or (not|no)\b", '"whether he would or not"'),
    ('syntax', r"\b(give|gave|giving|pay|paid|grant|granted) it (you|him|her|them|me)\b",
     'double object without "to"'),
    ('syntax', r"\bbid(s|ding)? (me|him|her|you|them|us)\b", '"bid me" for "tell me to"'),
    ('syntax', r"\bas I bid\b", '"as I bid"'),
    ('syntax', r"\b(it|that) (pleases|liked|likes) me\b", '"it pleases me"'),
    ('syntax', r"\bthe (less|better|more) (loss|blame|for it)\b", '"the less blame"'),
    ('syntax', r"\b\w+ you the (less|more|better)\b", '"I blame you the less"'),
    ('syntax', r"\b(like|love|liked|loved) (you|him|her|it) well\b", '"I like you well"'),
    ('syntax', r"\bwas dead these\b", '"dead these twenty years"'),
    ('syntax', r"\b(it was|it is|it's|was it) (he|she|they|we)\b(?! (who|that|did|had|was)\b)",
     '"it was he" (subject pronoun after "be")'),
    ('syntax', r"\b(stayed|stood|remained|lay|sat|sound|sounded|looked) so\b(?=[,.;:!?])",
     '"stayed so" for "stayed like that"'),
    ('syntax', r"\b(be|been|is|was|are|were) (paid|given|granted|sent) (you|him|her|them|me)\b",
     'passive with a bare indirect object ("paid you")'),
    ('syntax', r", nor (better|worse|more|less|will|would|could|can|shall)\b",
     '"nor" without "neither"'),
    ('syntax', r"^\W*so now (your|you|he|she|we|they|that|the)\b", '"so now" for "now that"'),
    ('syntax', r"\bhold aside\b", '"hold aside your hood"'),
    ('syntax', r"\b(be|was|is|turn|turned|play|played) (traitor|coward|recreant)\b",
     'no article before a role ("be traitor")'),
    # --- idiom -----------------------------------------------------------
    ('idiom', r"\b(yes|no), truly\b", '"yes, truly"'),
    ('idiom', r"\bquits(, \w+,)? of\b", '"quits of"'),
    ('idiom', r"\bremarking (it|them|that|this)\b", '"remarking it" for "remarking on it"'),
    ('idiom', r"\b(if it|it does|it doesn't|it does not|does it) displeases? (you|me|him|her)\b",
     '"if it doesn\'t displease you"'),
    ('idiom', r"\b(walked|walk|walks|went) about (her|him|them|the king|the queen)\b",
     '"walked about her" for "around"'),
    ('idiom', r"\b(fail|failed|fails) of\b", '"fail of" for "fail in"'),
    ('idiom', r"\b(need|needs|want) of (more|it|them|him|her)\b|\b(you've|I've|we've|he's|she's) need of\b",
     '"need of" for "need for"'),
    ('idiom', r"\b(joy|good|profit) of (it|them|him|her|this)\b|\bhad of (her|his|their|my|your)\b",
     '"have joy of it"'),
    ('idiom', r"\b(is|was|be|being|are|were) from home\b", '"from home" for "away"'),
    ('idiom', r"\bthese (two|three|four|five|six|seven|eight|nine|ten|twenty|many) (years|days|"
              r"weeks|months|winters)\b", '"these seven years" for "for seven years"'),
    ('idiom', r"\b(the|this) while\b(?! (I|you|he|she|we|they|it)\b)", '"the while"'),
    ('idiom', r"\b(think|thinks|thought) on\b", '"think on"'),
    ('idiom', r"\b(done|do|did) ill\b|\bI own it\b", '"done ill" / "I own it"'),
    ('idiom', r"\b(seemly|unseemly|in sooth|by my troth|in faith)\b", 'old idiom'),
    ('idiom', r"\b(told|tell|tells) over (his|her|their|my|the)\b", '"told over his sins"'),
    ('idiom', r"\blaid (it|them) by\b", '"laid it by"'),
    ('idiom', r"\bhold (yourself|myself|himself|it) (well paid|remedied|paid|excused|well)\b",
     '"hold yourself well paid"'),
    ('idiom', r"\bfare ?well\b(?=,)", '"fare well" as a verb'),
    ('idiom', r"\bhave done\.", '"and have done"'),
    ('idiom', r"\bwrong in me\b|\bill in me\b", '"wrong in me"'),
    ('idiom', r"\b(a fool's|your|my|his|her) asking\b", '"asking" as a noun'),
    ('idiom', r"\bcome what may of it\b|\bwhat may come of it\b", '"come what may of it"'),
]
_COMPILED = [(kind, re.compile(rx, re.IGNORECASE), what) for kind, rx, what in PATTERNS]

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
_CONTRACTIONS = [(re.compile(p, re.IGNORECASE), r) for p, r in (
    (r"\bcan't\b", 'can not'), (r"\bwon't\b", 'will not'), (r"\bshan't\b", 'shall not'),
    (r"n't\b", ' not'), (r"'ll\b", ' will'), (r"'re\b", ' are'), (r"'ve\b", ' have'),
    (r"'m\b", ' am'), (r"'d\b", ' would'))]
_WORD_RE = re.compile(r"[a-z]+(?:'[a-z]+)?")
_SENTENCE_RE = re.compile(r'[^.!?\n]+(?:[.!?]+["”’\']*|\n|$)')
_EXEMPT_HEADING_RE = re.compile(r'^#{1,6}\s+.*register exemptions', re.IGNORECASE)
_QUOTED_RE = re.compile(r'["“]([^"”]+)["”]')


@dataclass(frozen=True)
class Finding:
    scene_id: str
    kind: str          # word | syntax | idiom | echo
    what: str          # the pattern's name, or the source scene echoed
    evidence: str      # the matched words, or the shared run
    sentence: str      # the sentence it is in, as written


@dataclass(frozen=True)
class Exemptions:
    phrases: tuple[str, ...] = ()
    scenes: frozenset[str] = frozenset()


def read_exemptions(text: str) -> Exemptions:
    """The exemptions under the voice guide's "register exemptions" heading:
    quoted phrases (lowercased) and `scene:` ids. Empty without one."""
    phrases: list[str] = []
    scenes: set[str] = set()
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
        m = re.match(r'^scenes?:\s*(.+)$', body, re.IGNORECASE)
        if m:
            scenes.update(s.strip().strip('`') for s in re.split(r'[,;]', m.group(1)) if s.strip())
            continue
        phrases.extend(q.strip().lower() for q in _QUOTED_RE.findall(body) if q.strip())
    return Exemptions(tuple(phrases), frozenset(scenes))


def load_exemptions(project_dir: str) -> Exemptions:
    """`read_exemptions` of reference/voice-guide.md; empty without one."""
    path = os.path.join(project_dir, 'reference', 'voice-guide.md')
    try:
        with open(path, encoding='utf-8-sig') as f:
            return read_exemptions(f.read())
    except FileNotFoundError:
        return Exemptions()


def _normalize(text: str) -> list[str]:
    text = text.replace('’', "'").replace('‘', "'").lower()
    for rx, rep in _CONTRACTIONS:
        text = rx.sub(rep, text)
    return [_NORMALIZE.get(w, w) for w in _WORD_RE.findall(text)]


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
    low = sentence.lower()
    for p in phrases:
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
        for kind, rx, what in _COMPILED:
            for m in rx.finditer(sent):
                if not _exempt(sent, m.start(), m.end(), exemptions.phrases):
                    out.append(Finding(scene_id, kind, what, m.group(0), sent))
                    break
    return out


def _contains(seq: list[str], part: tuple[str, ...]) -> bool:
    n = len(part)
    return any(tuple(seq[i:i + n]) == part for i in range(len(seq) - n + 1))


def _ngrams(words: list[str], n: int) -> set[tuple[str, ...]]:
    return {tuple(words[i:i + n]) for i in range(len(words) - n + 1)}


def echo_findings(scene_id: str, text: str, source_texts: dict[str, str],
                  exemptions: Exemptions = Exemptions(), run: int = ECHO_RUN,
                  content: int = ECHO_CONTENT, dialogue_only: bool = True) -> list[Finding]:
    """Sentences sharing a run of `run`+ words with a source scene in
    `source_texts` ({label: prose}), the run holding a word that isn't a
    function word. One finding a sentence: the longest run."""
    if scene_id in exemptions.scenes or not source_texts:
        return []
    grams: dict[tuple[str, ...], str] = {}
    for label, prose in source_texts.items():
        for g in _ngrams(_normalize(prose), run):
            grams.setdefault(g, label)
    exempt_words = [_normalize(p) for p in exemptions.phrases]
    out = []
    for sent in (_dialogue_sentences(text) if dialogue_only else sentences(text)):
        words = _normalize(sent)
        best: tuple[int, int, str] | None = None
        i = 0
        while i <= len(words) - run:
            g = tuple(words[i:i + run])
            if (g in grams and sum(w not in _FUNCTION_WORDS for w in g) >= content
                    and not any(_contains(p, g) for p in exempt_words)):
                j = i + run
                while j < len(words) and tuple(words[j - run + 1:j + 1]) in grams:
                    j += 1
                if best is None or j - i > best[1] - best[0]:
                    best = (i, j, grams[g])
                i = j
            else:
                i += 1
        if best:
            out.append(Finding(scene_id, 'echo', f'shares words with {best[2]}',
                               ' '.join(words[best[0]:best[1]]), sent))
    return out


def source_texts_by_scene(project_dir: str) -> dict[str, dict[str, str]]:
    """{scene id: {"slug:source id": source prose}} from the source map, for
    the scenes whose sources resolve and have prose. {} with no `source:`
    block or no map. Raises source.SourceError on a config that can't be
    read."""
    from storyforge import source
    cfg = source.read_config(project_dir)
    if cfg is None:
        return {}
    rows = source.read_source_map(project_dir)
    if not rows:
        return {}
    cat = source.catalogue(project_dir, cfg)
    out: dict[str, dict[str, str]] = {}
    for sid, row in source.map_rows_by_scene(rows).items():
        texts = {}
        for ref in source.split_ids(row.get('source_scenes', '')):
            found = source.resolve_source_id(ref, cat)
            if found:
                prose = source.source_prose(project_dir, *found)
                if prose:
                    texts[f'{found[0]}:{found[1]}'] = prose
        if texts:
            out[sid] = texts
    return out


@dataclass
class Checked:
    findings: list[Finding]
    unchecked: dict[str, str]     # scene id -> why it couldn't be read
    echo_note: str                # why the echo check didn't run, or ''


def check_scenes(scene_ids: list[str], project_dir: str) -> Checked:
    """Both checks over the scenes given, in order."""
    from storyforge import source
    from storyforge.illustrations import read_scene_prose
    exemptions = load_exemptions(project_dir)
    echo_note = ''
    try:
        sources = source_texts_by_scene(project_dir)
        if not sources:
            echo_note = ('no source scenes to compare against (no `source:` block, '
                         'no reference/source-map.csv, or no imported source prose)')
    except (source.SourceError, OSError, ValueError) as e:
        sources = {}
        echo_note = f"the source can't be read ({e})"
    findings: list[Finding] = []
    unchecked: dict[str, str] = {}
    for sid in scene_ids:
        path = os.path.join(project_dir, 'scenes', f'{sid}.md')
        if not os.path.isfile(path):
            unchecked[sid] = 'no scene file'
            continue
        try:
            text = read_scene_prose(path)
        except (OSError, UnicodeDecodeError) as e:
            unchecked[sid] = f"can't be read ({e.__class__.__name__})"
            continue
        findings += pattern_findings(sid, text, exemptions)
        findings += echo_findings(sid, text, sources.get(sid, {}), exemptions)
    return Checked(findings, unchecked, echo_note)


def report_lines(checked: Checked) -> list[str]:
    """`score --register`'s output: a line per finding, then the counts."""
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
    if checked.echo_note:
        lines.append(f'WARNING: source echo not checked: {checked.echo_note}')
    for sid, why in checked.unchecked.items():
        lines.append(f'WARNING: {sid} not checked: {why}')
    return lines


#: the most findings a revision prompt lists (the rest are counted)
REVISION_MAX_FINDINGS = 40


def revision_section(project_dir: str, scene_ids: list[str]) -> str:
    """The `## Register` section of an adaptation's revision prompt: the
    re-voicing rule and this check's findings in the pass's scenes, for the
    reviser to fix. '' with no `source:` block, so other projects' prompts
    are unchanged. Raises source.SourceError on a `source:` block that
    can't be read."""
    from storyforge import source
    from storyforge.prompts_source import REVOICE_RULE
    if source.read_config(project_dir) is None:
        return ''
    checked = check_scenes(scene_ids, project_dir)
    lines = ['## Register', '', REVOICE_RULE]
    if checked.findings:
        lines += ['', 'The register check found these in this pass\'s scenes. Fix each '
                      'unless the voice guide exempts it; a source echo is the '
                      'translation\'s own words, to say again in this novel\'s:', '']
        for f in checked.findings[:REVISION_MAX_FINDINGS]:
            lines.append(f'- {f.scene_id}: "{f.sentence}" ({f.kind}: {f.evidence}; {f.what})')
        more = len(checked.findings) - REVISION_MAX_FINDINGS
        if more > 0:
            lines.append(f'- ...and {more} more of the same kinds: find them too.')
    return '\n'.join(lines) + '\n'
