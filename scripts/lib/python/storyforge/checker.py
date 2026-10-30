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
- Fails loud: a refusal, a reply cut off, a reply that isn't the schema, or
  a tool loop that never ends raises `CheckError`. There is no partial result.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field

from storyforge import ledger
from storyforge.api import (RefusalError, ToolInputError, ToolLoopError, ToolRun,
                            converse, extract_text, is_truncated)

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

MAX_SEARCH_HITS = 12
MAX_LEDGER_ROWS = 60
#: A passage longer than this is cut, around the match, in a search result
PASSAGE_CHARS = 700
MAX_TURNS = 24

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
    run: ToolRun | None = None


def _flat(text: str) -> str:
    return ' '.join(text.split())


def _norm(text: str) -> str:
    """Lowercased, whitespace collapsed, curly quotes and dashes made plain:
    how quotes are matched against the text."""
    text = (text.replace('‘', "'").replace('’', "'")
            .replace('“', '"').replace('”', '"')
            .replace('—', '-').replace('–', '-'))
    return _flat(text).lower()


def _contains(text: str, quote: str) -> bool:
    q = _norm(quote).strip(' ."\'')
    return bool(q) and q in _norm(text)


# ============================================================================
# The book, as the tools see it
# ============================================================================

@dataclass
class Book:
    """What the checker can look at: scene prose in reading order, the scene
    rows, and the ledger."""
    order: dict[str, int]
    scenes: dict[str, dict[str, str]]
    prose: dict[str, str]
    rows: list[dict[str, str]]

    @classmethod
    def load(cls, project_dir: str, scene_id: str, prose: str | None = None) -> 'Book':
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
        return cls(order, scenes, texts, ledger.load(project_dir))

    def where(self, sid: str, at: str) -> str:
        if sid not in self.order:
            return 'no scene'
        d = self.order[sid] - self.order[at]
        return 'this scene' if d == 0 else ('earlier' if d < 0 else 'later')


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
    lines = [f'{len(hits)} passage(s) contain all of: {", ".join(words)}'
             + (f' (first {MAX_SEARCH_HITS} in reading order)' if len(hits) > MAX_SEARCH_HITS else '')]
    for sid, para in hits[:MAX_SEARCH_HITS]:
        if len(para) > PASSAGE_CHARS:
            i = _norm(para).find(words[0])
            start = max(0, i - PASSAGE_CHARS // 2)
            para = ('…' if start else '') + para[start:start + PASSAGE_CHARS] + '…'
        lines.append(f'[{sid}, {book.where(sid, at)}] {para}')
    return '\n'.join(lines)


def _read_scene(book: Book, at: str, args: dict) -> str:
    sid = (args.get('scene_id') or '').strip()
    if sid == at:
        raise ToolInputError('that is the scene being checked; its text is in the prompt')
    if sid not in book.prose:
        raise ToolInputError(f'no scene {sid!r}; the scene list in the prompt has every id')
    return f'[{sid}, {book.where(sid, at)}]\n\n{book.prose[sid]}'


def _fact_line(row: dict, at: str, book: Book) -> str:
    sid = (row.get('scene_id') or '').strip()
    place = f'{sid}, {book.where(sid, at)}' if sid else 'backstory'
    kind = 'commitment' if ledger.is_commitment(row) else 'registry'
    quote = (row.get('quote') or '').strip()
    return (f'- {row["id"]} [{row.get("type")}, {row.get("mutable") or "state"}, {kind}, '
            f'{place}] {row.get("subject") or "-"}: {row.get("statement")}'
            + (f' — "{quote}"' if quote else ''))


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
    head = f'{len(out)} binding fact(s)' + (
        f'; the first {MAX_LEDGER_ROWS} in reading order' if len(out) > MAX_LEDGER_ROWS else '')
    return '\n'.join([head] + [_fact_line(r, at, book) for r in out[:MAX_LEDGER_ROWS]])


TOOLS = [
    {'name': 'search_manuscript',
     'description': 'Find the paragraphs of the other scenes that contain every word of '
                    'the query (case-insensitive; a word matches any word it starts). Use it '
                    'to find where a name, number, date, place, object or relationship is '
                    'set up elsewhere. Each hit names its scene and whether it is earlier or '
                    'later than the scene being checked.',
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
                    'Leave a filter empty to skip it. Each fact says where it was set up.',
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


def _brief_section(book: Book, project_dir: str, at: str) -> tuple[str, dict[str, str]]:
    """The brief's promises as prompt text, and registry id → statement for
    each promised registry fact (what `kept` may name)."""
    from storyforge.elaborate import get_scene
    scene = get_scene(at, os.path.join(project_dir, 'reference')) or {}
    lines, promised = [], {}
    for col in PROMISE_FIELDS:
        if (scene.get(col) or '').strip():
            lines.append(f'- **{col}**: {scene[col].strip()}')
    for fields, verb in ((REGISTRY_ENTERING_FIELDS, 'holds entering the scene'),
                         (REGISTRY_PROMISE_FIELDS, 'the scene must establish')):
        for col, type_ in fields.items():
            aliases = ledger.alias_map(ledger.view(book.rows, type_))
            by_id = {r['id']: r for r in book.rows}
            for item in _split_cell(scene.get(col, '')):
                rid = aliases.get(item.lower())
                if rid is None:
                    lines.append(f'- **{col}** ({verb}): "{item}" (not in the ledger)')
                    continue
                lines.append(f'- **{col}** ({verb}): {rid}: {by_id[rid]["statement"]}')
                if col in REGISTRY_PROMISE_FIELDS:
                    promised[rid] = by_id[rid]['statement']
    if not lines:
        return '', promised
    return ('\n## The brief\'s promises\n\n' + '\n'.join(lines) + '\n'), promised


def build_prompt(book: Book, at: str, brief_text: str) -> str:
    s = book.scenes.get(at, {})
    promise_rules = '' if not brief_text else (
        '\n**Broken promises.** Each item of the brief above is a promise. Report one the '
        'scene does not deliver (kind `broken-promise`; `fact_id` the registry id, or the '
        'brief field for outcome / key_actions / key_dialogue; `established_quote` the '
        'promised item; `established_scene` empty; `scene_quote` the scene\'s nearest '
        'words, or empty if nothing in the scene comes near). A close paraphrase keeps a '
        'key_dialogue promise. For each registry fact the scene must establish and does, '
        'add it to `kept` with the scene\'s words that establish it.\n')
    return f"""You are checking one scene of a novel for continuity, the way a careful reader would notice a slip.

## Scene being checked: {at}

Title: {s.get('title', '')}; POV: {s.get('pov') or '-'}; location: {s.get('location') or '-'}

{book.prose[at]}
{brief_text}
## Every scene, in reading order

{_scene_index(book, at)}

## What to report

**Contradictions.** Report each place where this scene contradicts something the book establishes elsewhere: in another scene (earlier or later) or in the ledger of recorded facts. Codes: PHY a physical state (injury, possession, where a person or object is), TIM time (dates, ages, elapsed time, time of day, durations), KNO who knows what, REL how people are related or connected, TRT a fixed trait (name, appearance, history, habit), WLD a rule or fact of the world, PRM a promise or threat a character made.

Use the tools before you report anything. For every specific claim in the scene that a reader could check (a name, number, age, date, elapsed time, kinship, who knows what, where someone or something is, an injury or possession, what a character promised), search the manuscript or the ledger for where it is set up. Read a scene in full when a passage is not enough.

Report only a real contradiction, both sides quoted:
- `scene_quote`: the scene's exact words that break it, copied verbatim.
- `established_scene` and `established_quote`: the other scene's id and its exact words, copied verbatim from a tool result; for a ledger fact with no scene, `established_scene` empty, `fact_id` its id and `established_quote` its statement.
- Not a contradiction: a character who lies, misremembers or is mistaken where the text signals it; a change the story shows happening; a vision, dream or story-within-the-story that the narrative frames as such; figurative language; anything you could not find established. When in doubt, leave it out: a false report costs the author more than a miss.
{promise_rules}
Return every finding, and an empty list when the scene is clean."""


# ============================================================================
# The check
# ============================================================================

def _verify(f: Finding, book: Book, at: str) -> str:
    """Why `f`'s quotes don't hold up ('' when they do)."""
    if f.scene_quote and not _contains(book.prose[at], f.scene_quote):
        return 'its scene quote is not in the scene'
    if f.kind == 'broken-promise':
        return ''
    if not f.scene_quote:
        return 'a contradiction with no scene quote'
    if f.established_scene:
        if f.established_scene not in book.prose:
            return f'{f.established_scene!r} is not a scene'
        if not _contains(book.prose[f.established_scene], f.established_quote):
            return f'its established quote is not in {f.established_scene}'
        return ''
    row = next((r for r in book.rows if r.get('id') == f.fact_id), None)
    if row is None:
        return f'it names no scene and {f.fact_id!r} is not a ledger fact'
    return ''


def check_scene(project_dir: str, scene_id: str, *, prose: str | None = None,
                promises: bool = True, model: str | None = None,
                log_file: str = '') -> CheckResult:
    """Check `scene_id` (its file, or `prose` in its place) against the rest
    of the book; with `promises`, against its brief too.

    Raises:
        CheckError: the scene can't be checked, or the check didn't finish
            (refusal, a reply cut off or off-schema, too many tool turns).
    """
    from storyforge.common import select_model
    book = Book.load(project_dir, scene_id, prose)
    brief_text, promised = _brief_section(book, project_dir, scene_id) if promises else ('', {})
    handlers = {
        'search_manuscript': lambda a: _search(book, scene_id, a),
        'read_scene': lambda a: _read_scene(book, scene_id, a),
        'query_ledger': lambda a: _query_ledger(book, scene_id, a),
    }
    try:
        run = converse(build_prompt(book, scene_id, brief_text), model or select_model('checking'),
                       TOOLS, handlers, max_tokens=8000, max_turns=MAX_TURNS,
                       label=f'check {scene_id}', output_schema=SCHEMA, log_file=log_file)
    except (RefusalError, ToolLoopError) as e:
        raise CheckError(f'{scene_id}: {e}') from e
    if is_truncated(run.response):
        raise CheckError(f'{scene_id}: the checker\'s reply was cut off at max_tokens')
    try:
        data = json.loads(extract_text(run.response))
        items, kept = data['findings'], data['kept']
    except (ValueError, KeyError, TypeError) as e:
        raise CheckError(f'{scene_id}: the checker\'s reply is not the schema ({e})') from e

    result = CheckResult(scene_id, run=run)
    for item in items:
        f = Finding(**{k: (item.get(k) or '').strip() for k in
                       ('kind', 'code', 'scene_quote', 'established_scene',
                        'established_quote', 'fact_id', 'explanation')})
        f.problem = _verify(f, book, scene_id)
        (result.unverified if f.problem else result.findings).append(f)
    for k in kept:
        rid, quote = (k.get('fact_id') or '').strip(), (k.get('quote') or '').strip()
        if rid not in promised:
            result.kept_unverified.append((rid, quote, 'not a fact the brief promises'))
        elif not _contains(book.prose[scene_id], quote):
            result.kept_unverified.append((rid, quote, 'the quote is not in the scene'))
        else:
            result.kept.append((rid, quote))
    return result
