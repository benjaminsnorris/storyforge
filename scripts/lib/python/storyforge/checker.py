"""The gate's checker: one scene against the book (rethink plan §3.2 step 2).

A tool-using model call (`api.converse`) reads the scene and reports, by
error code, every place it contradicts something the book has established,
and (with `promises=True`) every promise of its brief it doesn't keep. It
works the way the design note says the gate checks
(`docs/plans/2026-10-30-gate-ledger-design.md`): against every binding fact
in the ledger, registry facts and commitments alike, and against the prose
of the other scenes, which it searches and reads through tools rather than
getting one fixed bundle.

- `check_scene(project_dir, scene_id, ...)` → `CheckResult`.
- Every finding quotes the scene, and a contradiction quotes what it
  contradicts. A quote that isn't in the text it names makes the finding
  `unverified`: kept and returned apart from `findings`, never dropped, so
  the caller reports it.
- The book's bibles (`REFERENCE_DOCS`) go in the system prompt, whole, the
  way drafting sees them: a fact that lives only in a bible ("Marie is
  Claire's sister") can be contradicted, and a finding against one names
  the file as its `established_scene`. A missing, empty or unfilled
  template bible is left out (F-130), and the prompt names what is. They
  are sent uncapped, as drafting's shared context sends them, with their
  own cache breakpoint; one that can't be read as UTF-8 is a `CheckError`.
- Fails loud: a refusal, a reply cut off, a reply that isn't the schema, or
  a tool loop that never ends raises `CheckError`. There is no partial result.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field

from storyforge import ledger
from storyforge.quotes import normalize, quote_in, word_count
from storyforge.api import ToolInputError, ToolRun, converse, extract_text, is_truncated

#: Ledger type → the error code a contradiction of it carries (E1/E2's codes)
CODE_OF_TYPE = {'physical': 'PHY', 'timeline': 'TIM', 'knowledge': 'KNO',
                'relationship': 'REL', 'trait': 'TRT', 'world': 'WLD',
                'promise': 'PRM'}
CODES = tuple(CODE_OF_TYPE.values())

KINDS = ('contradiction', 'broken-promise')

#: Brief fields whose items are promises (the ones E4's judge counts as BPS);
#: interpretive fields (emotions, motifs, subtext) are notes, not promises
PROMISE_FIELDS = ('outcome', 'key_actions', 'key_dialogue')
REGISTRY_PROMISE_FIELDS = {'knowledge_out': 'knowledge', 'physical_state_out': 'physical'}
REGISTRY_ENTERING_FIELDS = {'knowledge_in': 'knowledge', 'physical_state_in': 'physical'}

#: Search hits shown: up to `FULL_HITS` as whole paragraphs (cut to
#: `PASSAGE_CHARS` around the match); past that, up to `MAX_SEARCH_HITS` as
#: `SNIPPET_CHARS` snippets. E4 run 5's checker searched "scar thumb", got 42
#: hits, saw the first 12 and missed the one it needed.
FULL_HITS = 12
MAX_SEARCH_HITS = 40
MAX_LEDGER_ROWS = 60
#: A passage longer than this is cut, around the match, in a search result
PASSAGE_CHARS = 700
SNIPPET_CHARS = 300
MAX_TURNS = 24
#: The reference docs the checker reads whole (the ones drafting's shared
#: context sends, and E4's judge reads)
REFERENCE_DOCS = ('character-bible.md', 'world-bible.md', 'systems-bible.md')

SCHEMA = {
    'type': 'object',
    'properties': {
        'findings': {'type': 'array', 'items': {
            'type': 'object',
            'properties': {
                'kind': {'type': 'string', 'enum': list(KINDS)},
                'code': {'type': 'string', 'enum': list(CODES)},
                'scene_quote': {'type': 'string'},
                'established_scene': {'type': 'string'},
                'established_quote': {'type': 'string'},
                'fact_id': {'type': 'string'},
                'explanation': {'type': 'string'},
            },
            'required': ['kind', 'code', 'scene_quote', 'established_scene',
                         'established_quote', 'fact_id', 'explanation'],
            'additionalProperties': False,
        }},
        'kept': {'type': 'array', 'items': {
            'type': 'object',
            'properties': {'fact_id': {'type': 'string'}, 'quote': {'type': 'string'}},
            'required': ['fact_id', 'quote'],
            'additionalProperties': False,
        }},
    },
    'required': ['findings', 'kept'],
    'additionalProperties': False,
}

#: SCHEMA plus `cleared`: the disputes the checker found are no contradiction.
#: Only sent when there are disputes, so a scene without any asks what it
#: always asked
DISPUTE_SCHEMA = {**SCHEMA,
                  'properties': {**SCHEMA['properties'],
                                 'cleared': {'type': 'array', 'items': {'type': 'string'}}},
                  'required': SCHEMA['required'] + ['cleared']}


@dataclass
class Dispute:
    """A registry fact extraction says the scene changes (supersedes, or ends
    a state its `resolves` doesn't end here): the checker must rule on it."""
    fact_id: str        # the registry fact
    statement: str      # its statement
    claim: str          # what extraction read in the scene


class CheckError(RuntimeError):
    """The check could not be completed; the message says why."""


@dataclass
class Finding:
    kind: str                 # one of KINDS
    code: str                 # one of CODES
    scene_quote: str          # the scene's words that break it
    established_scene: str    # where the broken fact is set up ('' for a ledger
                              # fact with no scene, or a brief promise)
    established_quote: str
    fact_id: str              # ledger id, or the brief field of a promise
    explanation: str
    problem: str = ''         # why it is unverified ('' when verified)

    def message(self) -> str:
        what = (f'contradicts {self.established_scene or "the ledger"}'
                if self.kind == 'contradiction' else 'breaks the brief')
        ref = f' [{self.fact_id}]' if self.fact_id else ''
        return f'{self.code} {what}{ref}: "{self.scene_quote}" — {self.explanation}'


@dataclass
class CheckResult:
    scene_id: str
    findings: list[Finding] = field(default_factory=list)
    unverified: list[Finding] = field(default_factory=list)
    #: (registry fact id, establishing quote) for each brief fact the prose
    #: was found to establish, quote verified
    kept: list[tuple[str, str]] = field(default_factory=list)
    #: (id, quote, why) for a `kept` item that didn't hold up: an id the brief
    #: doesn't promise, or a quote not in the scene
    kept_unverified: list[tuple[str, str, str]] = field(default_factory=list)
    #: brief items (`column: item`) written in words rather than naming a
    #: binding ledger fact: checked against their words (no quote to fill)
    unknown_brief_items: list[str] = field(default_factory=list)
    #: brief items naming a ledger fact that isn't binding (rejected,
    #: superseded, pending): an author problem, not checked
    stale_brief_items: list[str] = field(default_factory=list)
    #: disputes the checker ruled out (no contradiction)
    cleared: list[Dispute] = field(default_factory=list)
    #: disputes it neither reported as a contradiction nor cleared: they
    #: block the commit like an unverified finding
    unruled: list[Dispute] = field(default_factory=list)
    run: ToolRun | None = None


def _flat(text: str) -> str:
    return ' '.join(text.split())


_norm = normalize
_contains = quote_in

#: A `kept` quote shorter than this can't show a fact was established
MIN_KEPT_WORDS = 4


# ============================================================================
# The book, as the tools see it
# ============================================================================

@dataclass
class Book:
    """What the checker can look at: scene prose in reading order, the scene
    rows, the ledger, and the bibles (file name → text, only those with
    the author's own text)."""
    order: dict[str, int]
    scenes: dict[str, dict[str, str]]
    prose: dict[str, str]
    rows: list[dict[str, str]]
    reference: dict[str, str] = field(default_factory=dict)

    @classmethod
    def load(cls, project_dir: str, scene_id: str, prose: str | None = None,
             rows: list[dict[str, str]] | None = None) -> 'Book':
        """`rows` in place of the ledger on disk (the gate passes the ledger
        without the scene's earlier commitments)."""
        from storyforge.elaborate import _read_csv_as_map
        ref_dir = os.path.join(project_dir, 'reference')
        order = ledger.scene_order(project_dir)
        if scene_id not in order:
            raise CheckError(f'{scene_id} is not a scene in reference/scenes.csv')
        scenes = _read_csv_as_map(os.path.join(ref_dir, 'scenes.csv'))
        texts = {}
        for sid in order:
            path = os.path.join(project_dir, 'scenes', f'{sid}.md')
            if os.path.isfile(path):
                with open(path, encoding='utf-8') as f:
                    texts[sid] = f.read()
        if prose is not None:
            texts[scene_id] = prose
        if not (texts.get(scene_id) or '').strip():
            raise CheckError(f'{scene_id} has no prose to check')
        return cls(order, scenes, texts, ledger.load(project_dir) if rows is None else rows,
                   reference_docs(project_dir))

    def where(self, sid: str, at: str) -> str:
        if sid not in self.order:
            return 'no scene'
        d = self.order[sid] - self.order[at]
        return 'this scene' if d == 0 else ('earlier' if d < 0 else 'later')


def reference_docs(project_dir: str) -> dict[str, str]:
    """The bibles with the author's text, by file name, in `REFERENCE_DOCS`
    order. A missing or blank file, or one still identical to its template
    (`common.is_unfilled_template`), is left out: a template's guidance
    would read as the book's facts."""
    from storyforge.common import is_unfilled_template
    docs = {}
    for name in REFERENCE_DOCS:
        path = os.path.join(project_dir, 'reference', name)
        if not os.path.isfile(path):
            continue
        try:
            # utf-8-sig drops a BOM, as is_unfilled_template does
            with open(path, encoding='utf-8-sig') as f:
                text = f.read()
        except (OSError, UnicodeDecodeError) as e:
            raise CheckError(f'reference/{name} can\'t be read as UTF-8 text ({e}); '
                             f'the checker needs it') from e
        if text.strip() and not is_unfilled_template(path):
            docs[name] = text
    return docs


def _system(book: Book) -> list[dict] | None:
    """The bibles as the system prompt, or None when there are none. It is
    the same for every scene, and its own cache breakpoint lets each scene's
    check read it from cache (the request's automatic breakpoint, at the end,
    only serves the turns of one scene)."""
    if not book.reference:
        return None
    parts = [f'<reference file="{name}">\n{text.strip()}\n</reference>'
             for name, text in book.reference.items()]
    return [{'type': 'text', 'text': "The book's reference material, which every scene "
             'must agree with:\n\n' + '\n\n'.join(parts),
             'cache_control': {'type': 'ephemeral'}}]


def _reference_note(book: Book) -> str:
    if not book.reference:
        return ('The book has no reference material (no character, world or systems '
                'bible with its own text), so check against the other scenes and the '
                'ledger only.')
    return ('The reference material in the system prompt (' + ', '.join(book.reference)
            + ') also establishes facts: a scene that contradicts it is a contradiction, '
            'with `established_scene` the file name and `established_quote` its exact '
            'words.')


def _search(book: Book, at: str, args: dict) -> str:
    query = (args.get('query') or '').strip()
    words = [w for w in re.findall(r"[\w']+", query.lower()) if len(w) > 1]
    if not words:
        raise ToolInputError('give at least one word to search for')
    hits = []
    for sid in sorted(book.prose, key=book.order.get):
        if sid == at:
            continue
        for para in re.split(r'\n\s*\n', book.prose[sid]):
            low = _norm(para)
            if all(re.search(r'\b' + re.escape(w), low) for w in words):
                hits.append((sid, _flat(para)))
    if not hits:
        return f'No passage in another scene contains all of: {", ".join(words)}.'
    # Nearest first: the earlier scenes back from this one, then the later
    # ones forward (a slip is usually against what the reader saw last)
    here = book.order[at]
    hits.sort(key=lambda h: (book.order[h[0]] > here, abs(book.order[h[0]] - here)))
    shown = hits[:MAX_SEARCH_HITS]
    width = PASSAGE_CHARS if len(hits) <= FULL_HITS else SNIPPET_CHARS
    # Centre each cut on the query's longest word, the most specific
    key = max(words, key=len)
    lines = [f'{len(hits)} passage(s) contain all of: {", ".join(words)}; '
             + ('all shown' if len(hits) == len(shown) else f'the nearest {len(shown)} shown '
                f'(add a word to narrow the search)')
             + ('' if width == PASSAGE_CHARS else f', cut to {width} characters (read_scene '
                f'for a whole scene)') + '; nearest first, earlier scenes before later ones']
    for sid, para in shown:
        if len(para) > width:
            i = _norm(para).find(key)
            start = max(0, i - width // 2)
            para = ('…' if start else '') + para[start:start + width] + '…'
        lines.append(f'[{sid}, {book.where(sid, at)}] {para}')
    return '\n'.join(lines)


def _read_scene(book: Book, at: str, args: dict) -> str:
    sid = (args.get('scene_id') or '').strip()
    if sid == at:
        raise ToolInputError('that is the scene being checked; its text is in the prompt')
    if sid not in book.prose:
        raise ToolInputError(f'no scene {sid!r}; the scene list in the prompt has every id')
    return f'[{sid}, {book.where(sid, at)}]\n\n{book.prose[sid]}'


def _fact_line(row: dict, at: str, book: Book, superseded_by: dict[str, str]) -> str:
    """One fact for the model: where it was set up and, for a state, whether
    it still holds (where it ends, what superseded it)."""
    sid = (row.get('scene_id') or '').strip()
    place = f'{sid}, {book.where(sid, at)}' if sid else 'backstory'
    kind = 'commitment' if ledger.is_commitment(row) else 'registry'
    tags = [row.get('type') or '', row.get('mutable') or 'state', kind, place]
    ends = (row.get('resolves') or '').strip()
    if ends == 'never':
        tags.append('never ends')
    elif ends:
        tags.append(f'ends {ends}, {book.where(ends, at)}')
    if row['id'] in superseded_by:
        later = superseded_by[row['id']]
        tags.append(f'superseded by {later}')
    quote = (row.get('quote') or '').strip()
    return (f'- {row["id"]} [{", ".join(tags)}] {row.get("subject") or "-"}: '
            f'{row.get("statement")}' + (f' — "{quote}"' if quote else ''))


def _query_ledger(book: Book, at: str, args: dict) -> str:
    subject = (args.get('subject') or '').strip().lower()
    type_ = (args.get('type') or '').strip()
    text = (args.get('text') or '').strip().lower()
    if type_ and type_ not in ledger.TYPES:
        raise ToolInputError(f'type must be one of {", ".join(ledger.TYPES)} (or empty)')
    if not (subject or type_ or text):
        raise ToolInputError('give a subject, a type or some text to match')
    out = []
    for row in book.rows:
        if row.get('status') != 'binding':
            continue
        if type_ and row.get('type') != type_:
            continue
        if subject and subject not in {row.get('subject', '').lower()} | {
                k.lower() for k in ledger._split(row.get('known_by', ''))}:
            continue
        if text and text not in (row.get('statement', '') + ' ' + row.get('quote', '')
                                 + ' ' + row.get('aliases', '')).lower():
            continue
        out.append(row)
    if not out:
        return 'No binding fact matches.'
    out.sort(key=lambda r: book.order.get((r.get('scene_id') or '').strip(), -1))
    superseded_by = {}
    for r in book.rows:
        if r.get('status') == 'binding':
            for old in ledger._split(r.get('supersedes', '')):
                superseded_by.setdefault(old, r['id'])
    head = f'{len(out)} binding fact(s)' + (
        f'; the first {MAX_LEDGER_ROWS} in reading order' if len(out) > MAX_LEDGER_ROWS else '')
    return '\n'.join([head] + [_fact_line(r, at, book, superseded_by)
                               for r in out[:MAX_LEDGER_ROWS]])


TOOLS = [
    {'name': 'search_manuscript',
     'description': 'Find the paragraphs of the other scenes that contain every word of '
                    'the query (case-insensitive; a word matches any word it starts). Use it '
                    'to find where a name, number, date, place, object or relationship is '
                    'set up elsewhere. Hits come nearest first (earlier scenes, then later '
                    'ones), each naming its scene and whether it is earlier or later than '
                    'the scene being checked; when there are many, they are cut short and '
                    'the result says how many were left out: add a word to narrow it.',
     'input_schema': {'type': 'object', 'properties': {'query': {'type': 'string'}},
                      'required': ['query'], 'additionalProperties': False}},
    {'name': 'read_scene',
     'description': 'The full text of another scene, by id.',
     'input_schema': {'type': 'object', 'properties': {'scene_id': {'type': 'string'}},
                      'required': ['scene_id'], 'additionalProperties': False}},
    {'name': 'query_ledger',
     'description': "The book's recorded facts (the ledger): binding facts matching every "
                    'filter given. subject: a character or location id (also matches who '
                    'knows a fact); type: physical, timeline, knowledge, relationship, '
                    'trait, world or promise; text: words in the statement or its quote. '
                    'Leave a filter empty to skip it. Each fact says where it was set up '
                    'and, for a state, where it ends or what superseded it: a state that '
                    'ended before the scene no longer holds.',
     'input_schema': {'type': 'object', 'properties': {
         'subject': {'type': 'string'}, 'type': {'type': 'string'}, 'text': {'type': 'string'}},
         'required': ['subject', 'type', 'text'], 'additionalProperties': False}},
]


# ============================================================================
# The prompt
# ============================================================================

def _scene_index(book: Book, at: str) -> str:
    lines = []
    for sid in sorted(book.order, key=book.order.get):
        s = book.scenes.get(sid, {})
        mark = '  <- this scene' if sid == at else ''
        lines.append(f'- {sid}: {s.get("title", "")} (POV {s.get("pov") or "-"}, '
                     f'{s.get("location") or "-"}){mark}')
    return '\n'.join(lines)


def _split_cell(value: str) -> list[str]:
    return [v.strip() for v in (value or '').split(';') if v.strip()]


@dataclass
class Brief:
    """The brief as the checker uses it."""
    text: str = ''                                          # the prompt section
    promised: dict[str, str] = field(default_factory=dict)  # registry id → statement
    fields: dict[str, str] = field(default_factory=dict)    # promise field → text
    #: promise field → its items in words, each a whole promise
    items: dict[str, list[str]] = field(default_factory=dict)
    #: entering field → its items in words (not to be contradicted)
    entering: dict[str, list[str]] = field(default_factory=dict)
    unknown: list[str] = field(default_factory=list)        # brief items in words, no ledger fact
    stale: list[str] = field(default_factory=list)          # brief items naming a non-binding fact


def _brief(book: Book, project_dir: str, at: str) -> Brief:
    """The scene's brief: what holds entering it (not to be contradicted)
    and what it promises (to be delivered). A registry item is matched
    against every ledger fact, by id, statement or alias: a binding one is
    a fact; one that isn't binding (rejected, superseded) is the author's to
    fix and isn't checked (`stale`); none at all is an item in words."""
    from storyforge.elaborate import get_scene
    scene = get_scene(at, os.path.join(project_dir, 'reference')) or {}
    brief = Brief()
    by_id = {r['id']: r for r in book.rows}
    entering, promises = [], []
    for col in PROMISE_FIELDS:
        if (scene.get(col) or '').strip():
            brief.fields[col] = scene[col].strip()
            brief.items[col] = _split_cell(scene[col]) or [scene[col].strip()]
            promises.append(f'- **{col}**: {brief.fields[col]}')
    for fields, lines in ((REGISTRY_ENTERING_FIELDS, entering),
                          (REGISTRY_PROMISE_FIELDS, promises)):
        for col, type_ in fields.items():
            aliases = ledger.alias_map(ledger.view(book.rows, type_))
            for item in _split_cell(scene.get(col, '')):
                rid = aliases.get(item.lower())
                if rid is not None and by_id[rid].get('status') != 'binding':
                    brief.stale.append(f'{col}: {item} ({rid} is {by_id[rid].get("status")})')
                    continue
                if rid is None:
                    # Written in words rather than naming a ledger fact: still
                    # part of the brief, checked against its words
                    brief.unknown.append(f'{col}: {item}')
                    lines.append(f'- **{col}**: "{item}" (in words; no ledger fact names it)')
                    if col in REGISTRY_PROMISE_FIELDS:
                        brief.fields[col] = '; '.join(filter(None, [brief.fields.get(col), item]))
                        brief.items.setdefault(col, []).append(item)
                    else:
                        brief.entering.setdefault(col, []).append(item)
                    continue
                lines.append(f'- **{col}**: {rid}: {by_id[rid]["statement"]}')
                if col in REGISTRY_PROMISE_FIELDS:
                    brief.promised[rid] = by_id[rid]['statement']
    parts = []
    if entering:
        parts.append('\n## What holds entering the scene (from its brief)\n\n'
                     'The scene must not contradict these. They are not promises.\n\n'
                     + '\n'.join(entering) + '\n')
    if promises:
        parts.append("\n## The brief's promises\n\n" + '\n'.join(promises) + '\n')
    brief.text = ''.join(parts)
    return brief


def _disputes_text(disputes: list[Dispute]) -> str:
    if not disputes:
        return ''
    lines = '\n'.join(f'- {d.fact_id}: the plan records "{d.statement}"; extraction read '
                      f'in this scene: "{d.claim}"' for d in disputes)
    return ('\n## Facts the plan recorded that this scene may change\n\n'
            'Extraction thinks the scene changes each of these. Rule on every one: if '
            'the scene really contradicts it, report a contradiction with `fact_id` its '
            'id, `established_scene` empty and `established_quote` its statement; if it '
            'doesn\'t (the scene adds detail, or the change is one the story shows), put '
            'its id in `cleared`.\n\n' + lines + '\n')


def build_prompt(book: Book, at: str, brief_text: str,
                 disputes: list[Dispute] | None = None) -> str:
    s = book.scenes.get(at, {})
    promise_rules = '' if "## The brief's promises" not in brief_text else (
        "\n**Broken promises.** Each item under \"The brief's promises\" is a promise. "
        'Report one the scene does not deliver (kind `broken-promise`; `fact_id` the registry id, or the '
        'brief field for outcome / key_actions / key_dialogue or for an item written in '
        'words; `established_quote` the '
        'promised item; `established_scene` empty; `scene_quote` the scene\'s nearest '
        'words, or empty if nothing in the scene comes near). A close paraphrase keeps a '
        'key_dialogue promise. For each registry fact the scene must establish and does, '
        'add it to `kept` with the scene\'s words that establish it, copied verbatim (a '
        'full clause or sentence). A fact that holds entering the scene and is '
        'contradicted is a contradiction, not a broken promise: for one written in '
        'words, `fact_id` is its brief field and `established_quote` the item.\n')
    return f"""You are checking one scene of a novel for continuity, the way a careful reader would notice a slip.

## Scene being checked: {at}

Title: {s.get('title', '')}; POV: {s.get('pov') or '-'}; location: {s.get('location') or '-'}

{book.prose[at]}
{brief_text}{_disputes_text(disputes or [])}
## Every scene, in reading order

{_scene_index(book, at)}

## What to report

**Contradictions.** Report each place where this scene contradicts something the book establishes elsewhere: in another scene (earlier or later), in the reference material, or in the ledger of recorded facts. {_reference_note(book)} Codes: PHY a physical state (injury, possession, where a person or object is), TIM time (dates, ages, elapsed time, time of day, durations), KNO who knows what, REL how people are related or connected, TRT a fixed trait (name, appearance, history, habit), WLD a rule or fact of the world, PRM a promise or threat a character made.

Use the tools before you report anything. For every specific claim in the scene that a reader could check (a name, number, age, date, elapsed time, kinship, who knows what, where someone or something is, an injury or possession, what a character promised), search the manuscript or the ledger for where it is set up. Read a scene in full when a passage is not enough.

Report only a real contradiction, both sides quoted:
- `scene_quote`: the scene's exact words that break it, copied verbatim.
- `established_scene` and `established_quote`: the other scene's id and its exact words, copied verbatim from a tool result (or a reference file's name and its exact words); for a ledger fact with no scene, `established_scene` empty, `fact_id` its id and `established_quote` its statement.
- Not a contradiction: a character who lies, misremembers or is mistaken where the text signals it; a change the story shows happening; a vision, dream or story-within-the-story that the narrative frames as such; figurative language; anything you could not find established. When in doubt, leave it out: a false report costs the author more than a miss.
{promise_rules}
Return every finding, and an empty list when the scene is clean."""


# ============================================================================
# The check
# ============================================================================

def _verify(f: Finding, book: Book, at: str, brief: Brief) -> str:
    """Why `f`'s quotes don't hold up ('' when they do). A broken promise
    must name a promise the brief makes: a promised registry id, or a
    promise field whose text holds its `established_quote`; under another
    id, a quote found in a promise field's text verifies it, and `fact_id`
    becomes that field."""
    if f.scene_quote and not _contains(book.prose[at], f.scene_quote):
        return 'its scene quote is not in the scene'
    if f.kind == 'broken-promise':
        if f.fact_id in brief.promised:
            return ''
        if f.fact_id in brief.fields:
            whole = any(_whole_item(i, f.established_quote)
                        for i in brief.items.get(f.fact_id, []))
            inside = (_contains(brief.fields[f.fact_id], f.established_quote)
                      and word_count(f.established_quote) >= MIN_KEPT_WORDS)
            return ('' if whole or inside
                    else f'its promised item is not in the brief\'s {f.fact_id} (a whole '
                         f'item, or {MIN_KEPT_WORDS}+ words of it)')
        # A made-up id for an item the brief does make: found when its quote
        # is one whole item, of one field only
        fields_ = [col for col, items in brief.items.items()
                   if any(_whole_item(item, f.established_quote) for item in items)]
        if len(fields_) == 1:
            f.fact_id = fields_[0]
            return ''
        return (f'{f.fact_id!r} is not a promise of this scene\'s brief'
                + (' (its quote matches items in more than one field)' if fields_ else ''))
    if not f.scene_quote:
        return 'a contradiction with no scene quote'
    if not f.established_scene and f.fact_id in brief.entering:
        return ('' if any(_whole_item(i, f.established_quote)
                          for i in brief.entering[f.fact_id])
                else f'its established quote is not an item of the brief\'s {f.fact_id}')
    name = os.path.basename(f.established_scene)
    if name in book.reference:
        f.established_scene = name
        return ('' if _contains(book.reference[name], f.established_quote)
                else f'its established quote is not in {name}')
    if name in REFERENCE_DOCS:
        return f'{name} was not given to the checker (missing, empty or still the template)'
    if f.established_scene:
        if f.established_scene not in book.prose:
            return f'{f.established_scene!r} is not a scene'
        if not _contains(book.prose[f.established_scene], f.established_quote):
            return f'its established quote is not in {f.established_scene}'
        return ''
    row = next((r for r in book.rows if r.get('id') == f.fact_id
                and r.get('status') == 'binding'), None)
    if row is None:
        return f'it names no scene and {f.fact_id!r} is not a binding ledger fact'
    return ''


def _whole_item(item: str, quote: str) -> bool:
    """Whether `quote` is the brief item `item` (normalized), not a word or
    two found inside it."""
    return bool(quote.strip()) and normalize(item).strip(' .;') == normalize(quote).strip(' .;')


def check_scene(project_dir: str, scene_id: str, *, prose: str | None = None,
                promises: bool = True, model: str | None = None,
                log_file: str = '', rows: list[dict[str, str]] | None = None,
                disputes: list[Dispute] | None = None) -> CheckResult:
    """Check `scene_id` (its file, or `prose` in its place) against the rest
    of the book; with `promises`, against its brief too. `rows` replaces the
    ledger on disk. `disputes` are registry facts extraction says the scene
    changes: each must come back as a contradiction or `cleared`, else it is
    `unruled`.

    Raises:
        CheckError: the scene can't be checked, or the check didn't finish
            (refusal, an API failure, a reply cut off or off-schema, too many
            tool turns). It carries the exchange so far as `.run` when there
            was one.
    """
    from storyforge.common import select_model
    book = Book.load(project_dir, scene_id, prose, rows)
    brief = _brief(book, project_dir, scene_id) if promises else Brief()
    handlers = {
        'search_manuscript': lambda a: _search(book, scene_id, a),
        'read_scene': lambda a: _read_scene(book, scene_id, a),
        'query_ledger': lambda a: _query_ledger(book, scene_id, a),
    }
    try:
        run = converse(build_prompt(book, scene_id, brief.text, disputes),
                       model or select_model('checking'),
                       TOOLS, handlers, max_tokens=8000, max_turns=MAX_TURNS,
                       label=f'check {scene_id}', system=_system(book),
                       output_schema=DISPUTE_SCHEMA if disputes else SCHEMA,
                       log_file=log_file)
    except RuntimeError as e:   # RefusalError, ToolLoopError, an API failure
        error = CheckError(f'{scene_id}: {e}')
        error.run = getattr(e, 'run', None)
        raise error from e
    if is_truncated(run.response):
        raise CheckError(f'{scene_id}: the checker\'s reply was cut off at max_tokens')
    try:
        data = json.loads(extract_text(run.response))
        items, kept = data['findings'], data['kept']
        cleared = set(data['cleared']) if disputes else set()
    except (ValueError, KeyError, TypeError) as e:
        raise CheckError(f'{scene_id}: the checker\'s reply is not the schema ({e})') from e

    result = CheckResult(scene_id, run=run, unknown_brief_items=brief.unknown,
                         stale_brief_items=brief.stale)
    for item in items:
        f = Finding(**{k: (item.get(k) or '').strip() for k in
                       ('kind', 'code', 'scene_quote', 'established_scene',
                        'established_quote', 'fact_id', 'explanation')})
        f.problem = _verify(f, book, scene_id, brief)
        (result.unverified if f.problem else result.findings).append(f)
    for k in kept:
        rid, quote = (k.get('fact_id') or '').strip(), (k.get('quote') or '').strip()
        if rid not in brief.promised:
            result.kept_unverified.append((rid, quote, 'not a fact the brief promises'))
        elif not _contains(book.prose[scene_id], quote):
            result.kept_unverified.append((rid, quote, 'the quote is not in the scene'))
        elif word_count(quote) < MIN_KEPT_WORDS:
            result.kept_unverified.append((rid, quote, f'fewer than {MIN_KEPT_WORDS} words'))
        else:
            result.kept.append((rid, quote))
    reported = {f.fact_id for f in result.findings + result.unverified}
    for d in disputes or []:
        if d.fact_id in reported:
            continue            # ruled a contradiction: a finding
        (result.cleared if d.fact_id in cleared else result.unruled).append(d)
    return result
