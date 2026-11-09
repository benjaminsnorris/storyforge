"""The gate's question layer: narrow yes/no questions from the ledger (#649, plan A3).

The open checker (`storyforge.checker`) is asked to find contradictions,
and "find contradictions" invites findings; the gate takes the union of
two such readings (`checker.merge_readings`). The typed checks
(`storyforge.continuity`, #648) compare in code what can be typed: life,
place, possession, knowledge, injury, names, elapsed time, the sky. This
covers what they can't, the facts that live only in a ledger `statement`,
by asking about each one narrowly:

> Established in `nephew-visits-scrooge`: "Scrooge has always refused his
> nephew's invitations to dine." Question: Does this scene show or say
> something about Ebenezer Scrooge that this fact rules out? Answer yes or
> no. If yes, quote the scene's words.

- **Which facts** (`facts_to_ask`): binding ledger rows of every type but
  `promise` (`QUESTION_TYPES`) that hold for the scene: a fixed fact from
  any other scene or from before the book, a `state` fact only while it is
  in force entering the scene (`ledger.active_states`). A fact a typed
  check compares by code is left out, and `continuity.covered_fact_ids` is
  the one source for that (knowledge facts someone knows: the possession
  and injury checks read the prose's records, not ledger rows, so every
  `physical` row is asked).
- **Only about who is there** (`present_subjects`): a fact is asked when
  its subject (an id, name or alias, through the registries) is present by
  the scene's extracted cast (its typed state's `at` records), its places
  (its scenes.csv `location`s, or a place an `at` record names) or a
  registry name its prose uses (someone only talked about, remembered or
  dead). A subject in no registry (a group, a concept) can't be placed, so
  its facts are asked in every scene; a fact with no subject, or about a
  registry entry the scene doesn't have, isn't asked, and the notes count
  both. So the number of questions scales with the scene, not the ledger.
- **Storyforge writes the questions** (`question_for`), from the fact's
  type, subject and statement; no model writes them.
- **Each is asked twice** (`yes_no.ask`, the stage sheet's machinery, #647):
  all of a scene's questions in one call per asking, the second in reverse
  order, on the smallest model that holds the question set's floors
  (`resolve_model`: `STORYFORGE_QUESTIONS_MODEL`, else the extraction tier).
  A finding is kept only when **both** answers are `yes` **and** the quote
  verifies (`quotes.quote_in`): the intersection of narrow readings. A
  split answer, or two yeses with no quote in the scene, is a note, never a
  finding.
- **Disputes** (registry facts extraction says the scene changes,
  `checker.Dispute`) are asked the same way, each fact once (a disputed
  fact isn't also asked plainly), with the doubt leaning the other way:
  two yeses with a verified quote are a contradiction, two noes clear it,
  anything else leaves it unruled, which blocks the commit as the open
  checker's does.
- **The brief's promises** (`promises_for`, `ask_promises`) are their own
  call, asked twice: does the scene deliver each item of its brief? Two
  noes are a broken promise (advisory, unless a `must:` beat, #642), two
  yeses with a verified quote deliver it and fill a promised registry
  fact's blank quote (`kept`, as the open checker's), and anything else is a
  note, or for a `must:` beat an unverified broken promise, which blocks.
  The brief's entering items written in words are asked as facts.

Findings are `checker.Finding`s, contradictions with the code of the fact's
type (TRT, REL, PHY, WLD, KNO, TIM), set against the fact's scene and quote (the
ledger and its statement when it has neither), so the gate classifies,
fixes and accepts them like the open checker's. The gate uses this in
place of the open checker when `gate.GATE_CHECK_METHOD` is `questions`
(`storyforge check --questions`); the open checker stays the default until
this layer and the typed checks match its recall on the frozen E4 and E8.
The fixed labelled question set is `evals/suites/question_set.py`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from storyforge import yes_no
from storyforge.checker import CODE_OF_TYPE, Dispute, Finding
from storyforge.quotes import quote_in

#: The ledger types asked about: every type but `promise` (a set-up the
#: story pays off, not a fact a scene contradicts). Within them, a fact a
#: typed check compares by code (`continuity.covered_fact_ids`, the one
#: source: knowledge facts someone knows) is not asked. In this order, which
#: is the order they're asked in (the cap cuts from the end)
QUESTION_TYPES = ('trait', 'relationship', 'physical', 'world', 'knowledge', 'timeline')
#: Overrides the model (default the extraction tier)
MODEL_ENV = 'STORYFORGE_QUESTIONS_MODEL'
ASKINGS = yes_no.ASKINGS
#: The most questions asked per scene, disputes first (the rest are named
#: in the notes; a dispute past it is unruled). The brief's promises are
#: their own call with their own cap
MAX_QUESTIONS = 30

SCHEMA = {
    'type': 'object',
    'properties': {'answers': {'type': 'array', 'items': {
        'type': 'object',
        'properties': {'n': {'type': 'integer'},
                       'answer': {'type': 'string', 'enum': ['yes', 'no']},
                       'quote': {'type': 'string'},
                       'why': {'type': 'string'}},
        'required': ['n', 'answer', 'quote', 'why'],
        'additionalProperties': False,
    }}},
    'required': ['answers'],
    'additionalProperties': False,
}

PROMPT = """You check one scene of a novel against facts the book has already established. Each question gives one fact, where the book established it, and asks whether this scene contradicts it.

Answer `yes` only when the scene itself shows or says something that cannot be true if the fact holds, and put in `quote` the scene's words that do, copied exactly: the shortest clause that shows it. Answer `no` when the scene agrees with the fact, says nothing about it, or only seems to differ: a character's mistake, lie, joke or figure of speech, something remembered, dreamed or imagined, or a change the scene itself shows happening. When in doubt, `no`, with `quote` empty. Give a one-sentence reason in `why`.

## Scene: {scene_id}

{prose}

## Questions

{questions}"""

PROMISE_PROMPT = """You check whether one scene of a novel delivers what its brief planned. Each question gives one item of the scene's brief and asks whether the scene delivers it.

Answer `yes` when the scene itself shows or says it happening, in substance: its words and order may differ from the brief's. Put in `quote` the scene's words that deliver it, copied exactly: the shortest full clause or sentence that shows it. Answer `no` when the scene leaves it out, has something else happen instead, or has it only planned, hoped for, feared or remembered, with `quote` empty. Give a one-sentence reason in `why`.

## Scene: {scene_id}

{prose}

## Questions

{questions}"""


class QuestionError(RuntimeError):
    """The questions could not be asked; the message says why."""


@dataclass(frozen=True)
class Question:
    fact_id: str
    #: the fact's ledger type (its finding's code is `CODE_OF_TYPE[type]`)
    type: str
    subject: str
    statement: str
    #: the scene that established it ('' for the ledger: before the book,
    #: or no scene, or the brief's entering items)
    established_scene: str
    established_quote: str
    text: str
    #: the dispute this question rules on (None for a plain fact): two noes
    #: clear it, anything but a finding or that leaves it unruled
    dispute: Dispute | None = None

    @property
    def code(self) -> str:
        """The finding's code. Raises ValueError for a type with none:
        nothing is filed under a guessed code."""
        if self.type not in CODE_OF_TYPE:
            raise ValueError(f'{self.fact_id}: type {self.type!r} has no finding code')
        return CODE_OF_TYPE[self.type]


@dataclass(frozen=True)
class Promise:
    """One item of the scene's brief, asked whether the scene delivers it."""
    #: `item` (a promise field's item, or a registry promise in words),
    #: `promised` (a binding registry fact the brief promises: delivered,
    #: its quote is filled) or `planned` (a planned fact: delivered, its
    #: quote is filled; not delivered is a departure, never an error)
    kind: str
    #: the finding's `fact_id`: the brief field for an item, the fact's id
    #: otherwise
    fact_id: str
    #: the brief field it comes from ('' for a planned fact)
    field: str
    #: the brief's words as written (a `must:` marker kept): a broken
    #: promise's `established_quote`, so the gate can tell a `must` beat
    raw: str
    #: what the model is shown (no marker)
    text: str

    @property
    def must(self) -> bool:
        from storyforge.must import is_must
        return self.kind == 'item' and is_must(self.raw)


@dataclass
class Selection:
    """What `facts_to_ask` chose, and what it didn't, by fact id."""
    facts: list[dict] = field(default_factory=list)
    #: holding facts with no subject: their presence can't be told, not asked
    no_subject: list[str] = field(default_factory=list)
    #: holding facts about a registry character or place that isn't in the
    #: scene (not present, not named in its prose): not asked
    absent: list[str] = field(default_factory=list)
    #: of `facts`, those whose subject is in no registry (a group, a concept,
    #: an object): they can't be placed, so they're asked in every scene
    unplaced: list[str] = field(default_factory=list)


@dataclass
class QuestionResult:
    scene_id: str
    findings: list[Finding] = field(default_factory=list)
    #: what couldn't be asked or answered, and why (never silent)
    notes: list[str] = field(default_factory=list)
    #: fact and dispute questions asked (each `ASKINGS` times)
    asked: int = 0
    #: questions with split answers (a note)
    split: int = 0
    #: questions answered yes twice with no quote in the scene (a note)
    misquoted: int = 0
    #: disputes both askings said the scene doesn't contradict
    cleared: list[Dispute] = field(default_factory=list)
    #: disputes with no ruling (split, misquoted, past the cap, no fact to
    #: ask about): they block
    unruled: list[Dispute] = field(default_factory=list)
    #: the subjects found present (normalized ids), for the log
    present: list[str] = field(default_factory=list)
    #: the brief's promises asked (each `ASKINGS` times)
    promises_asked: int = 0
    #: a `must:` beat neither delivered nor broken by both askings (split,
    #: or delivered with no quote in the scene): a broken promise in doubt,
    #: which blocks, as a wrong stop costs a look and a wrong pass loses the
    #: author's beat
    unverified: list[Finding] = field(default_factory=list)
    #: (fact id, quote) for each promised or planned fact the scene was
    #: found to establish, quote verified: the gate fills its quote
    kept: list[tuple[str, str]] = field(default_factory=list)
    #: (id, quote, why) for one found established whose quote didn't hold up
    kept_unverified: list[tuple[str, str, str]] = field(default_factory=list)
    #: planned facts the scene doesn't establish (#568: not an error)
    plan_departures: list[Finding] = field(default_factory=list)
    #: as `checker.CheckResult`'s, from the brief
    unknown_brief_items: list[str] = field(default_factory=list)
    stale_brief_items: list[str] = field(default_factory=list)


# ============================================================================
# Which facts, about whom
# ============================================================================

def _norm(text: str) -> str:
    from storyforge.ledger import _norm as ledger_norm
    return ledger_norm(text)


def _lookup(name: str, *maps: dict[str, str]) -> str:
    """`name` (a registry id, name or alias, any case or spacing) as its
    registry id, normalized; else the name itself, normalized."""
    key = ' '.join((name or '').split()).lower()
    for m in maps:
        for k in (key, key.removeprefix('the ')):
            if k in m:
                return _norm(m[k])
    return _norm(key)


def present_subjects(records, chars: dict[str, str], places: dict[str, str],
                     location: str = '', *, prose: str = '',
                     names: dict[str, set[str]] | None = None) -> set[str]:
    """The subjects present in the scene, normalized (`ledger._norm`): each
    `at` record's person (a registry id through `chars`, a lower-case name
    or alias → id; else the name itself), each place an `at` record names
    that `places` knows, each of the scene's own `location`s (scenes.csv's
    `;` array), and each registry subject its `prose` names as a whole word
    (`names`: `ledger.subject_names`, id → its names and aliases), so a
    character only talked about, remembered or dead is asked about too."""
    from storyforge.ledger import _mentions
    out = set()
    for r in records or []:
        if getattr(r, 'type', '') != 'at':
            continue
        if ' '.join((r.who or '').split()):
            out.add(_lookup(r.who, chars))
        where = ' '.join((r.item or '').split()).lower()
        if where and (where in places or where.removeprefix('the ') in places):
            out.add(_lookup(where, places))
    for loc in (location or '').split(';'):
        if loc.strip():
            out.add(_lookup(loc, places))
    if prose and names:
        cache: dict = {}
        out |= {sid for sid in names if sid not in out and _mentions(prose, sid, names, cache)}
    return out - {''}


def facts_to_ask(rows: list[dict], scene_id: str, order: dict[str, int],
                 present: set[str], *, registry: set[str] | frozenset = frozenset(),
                 chars: dict[str, str] | None = None,
                 places: dict[str, str] | None = None) -> Selection:
    """The ledger facts to ask `scene_id` about, in type order then reading
    order, and what was left out. A fact holds for the scene when it is
    binding, of `QUESTION_TYPES`, no typed check compares it
    (`continuity.covered_fact_ids`) and it is not the scene's own: a fixed
    one (or one with no `mutable`) from any other scene or none, unless a
    binding fact supersedes it; a `state` one while in force entering the
    scene. A holding fact is asked when its subject (through `chars` and
    `places`, the registries' alias maps) is `present`, or is in no
    `registry` (normalized registry ids: a group or concept can't be placed,
    so it's asked everywhere); with no subject, or about a registry entry
    the scene doesn't have, it isn't."""
    from storyforge.continuity import covered_fact_ids
    from storyforge.ledger import active_states
    covered = covered_fact_ids(rows)
    candidates = [r for r in rows if (r.get('status') or '') == 'binding'
                  and (r.get('type') or '').strip() in QUESTION_TYPES
                  and r.get('id') not in covered
                  and (r.get('scene_id') or '').strip() != scene_id]
    superseded = {old.strip() for r in rows if (r.get('status') or '') == 'binding'
                  for old in (r.get('supersedes') or '').split(';') if old.strip()}
    in_force = {r['id'] for r in active_states(rows, scene_id, order, entering=True)} \
        if scene_id in order else set()
    holding = [r for r in candidates
               if (r['id'] in in_force if (r.get('mutable') or '') == 'state'
                   else r['id'] not in superseded)]
    out = Selection()
    asked = []
    for r in holding:
        subject = (r.get('subject') or '').strip()
        key = _lookup(subject, chars or {}, places or {})
        if not subject:
            out.no_subject.append(r['id'])
        elif key in present:
            asked.append(r)
        elif key not in registry:
            asked.append(r)
            out.unplaced.append(r['id'])
        else:
            out.absent.append(r['id'])
    rank = {t: n for n, t in enumerate(QUESTION_TYPES)}

    def where(r: dict) -> int:
        return order.get((r.get('scene_id') or '').strip(), -1)
    out.facts = sorted(asked, key=lambda r: (rank[r['type'].strip()], where(r), r['id']))
    return out


_ASKS = {
    'trait': 'Does this scene show or say something about {name} that this fact rules out?',
    'relationship': 'Does this scene show or say something about {name} and the others '
                    'this fact names that it rules out?',
    'physical': 'Does this scene describe {name} or what {name} has or can do in a way this '
                'fact rules out?',
    'world': 'Does this scene show {name} or how the world works in a way this fact rules '
             'out?',
    'knowledge': 'Does this scene show or say something about {name} and what is known that '
                 'this fact rules out?',
    'timeline': 'Does this scene place {name} or its events in time in a way this fact rules '
                'out?',
}


def question_for(row: dict, name: str, order: dict[str, int] | None = None) -> Question:
    """The question for one ledger fact, written by code from its type,
    subject (`name`, as the book names it) and statement. Its established
    scene is the fact's scene when that is a scene of the book (`order`;
    None: any), else '' (the ledger). Raises ValueError for a type not in
    `QUESTION_TYPES`."""
    type_ = (row.get('type') or '').strip()
    if type_ not in _ASKS:
        raise ValueError(f'{row.get("id", "")}: type {type_!r} is not asked about')
    scene = (row.get('scene_id') or '').strip()
    if order is not None and scene not in order:
        scene = ''
    statement = ' '.join((row.get('statement') or '').split())
    quote = ' '.join((row.get('quote') or '').split()) if scene else ''
    return Question(fact_id=row.get('id', ''), type=type_, subject=name, statement=statement,
                    established_scene=scene, established_quote=quote or statement,
                    text=_ASKS[type_].format(name=name))


#: brief entering fields → the ledger type an item in words is asked as
_ENTERING_TYPES = {'knowledge_in': 'knowledge', 'physical_state_in': 'physical'}


def entering_question(col: str, item: str) -> Question:
    """The question for a brief item that holds entering the scene, written
    in words (no ledger fact names it): the open checker's entering items.
    A finding's `fact_id` is the field, its established quote the item."""
    text = ' '.join(item.split())
    return Question(fact_id=col, type=_ENTERING_TYPES.get(col, 'physical'), subject='',
                    statement=text, established_scene='', established_quote=text,
                    text='The brief has this holding as the scene opens. Does the scene show '
                         'or say something this rules out?')


def dispute_question(d: Dispute, row: dict, name: str = '') -> Question:
    """The question for a dispute: extraction read the scene as changing
    the registry fact `row`; does it contradict it? The doubt goes to `yes`
    (the open checker left a doubtful dispute unruled, which blocks: a
    `yes` with a quote blocks as a contradiction, without one it is
    unruled), where the plain questions' goes to `no`."""
    scene = (row.get('scene_id') or '').strip()
    claim = ' '.join(d.claim.split())
    took = (f'A reader took this scene to change the fact: "{claim}". ' if claim
            else 'A reader took this scene to change the fact. ')
    return Question(fact_id=d.fact_id, type=(row.get('type') or '').strip(),
                    subject=name or (row.get('subject') or '').strip(),
                    statement=' '.join(d.statement.split()), established_scene=scene,
                    established_quote=' '.join((row.get('quote') or '').split())
                    or ' '.join(d.statement.split()),
                    text=took + 'Does the scene contradict the fact, so that it no longer '
                         'holds as stated? Answer `no` only when the scene clearly leaves it '
                         'standing (it adds detail, or shows the change happening); if you '
                         'can\'t tell, answer `yes` and quote the words the reader took as '
                         'the change.',
                    dispute=d)


# ============================================================================
# Asking
# ============================================================================

def _block(n: int, q: Question) -> str:
    where = (f'Established in {q.established_scene}' if q.established_scene
             else 'Established before the story or in the ledger')
    said = (f'\n   Its words there: "{q.established_quote}"'
            if q.established_scene and q.established_quote and q.established_quote != q.statement
            else '')
    return f'{n}. {where}: "{q.statement}"{said}\n   Question: {q.text}'


def _numbered(blocks: list[str], asking: int) -> str:
    order = list(enumerate(blocks, start=1))
    if asking > 1:
        order.reverse()
    return '\n\n'.join(b.format(n=n) for n, b in order)


def _independent(text: str, asking: int) -> str:
    if asking > 1:
        text += f'\n\nThis is independent asking {asking}: answer each question afresh.'
    return text


def build_prompt(scene_id: str, prose: str, questions: list[Question], asking: int = 1) -> str:
    """The questions, numbered from 1 in `questions`' order. A later asking
    lists them in reverse and says which it is (`yes_no`)."""
    order = list(enumerate(questions, start=1))
    if asking > 1:
        order.reverse()
    return _independent(PROMPT.format(scene_id=scene_id, prose=prose.strip(),
                                      questions='\n\n'.join(_block(n, q) for n, q in order)),
                        asking)


def resolve_model(model: str | None = None) -> str:
    from storyforge.common import select_model
    return model or os.environ.get(MODEL_ENV) or select_model('extraction')


def max_tokens(count: int) -> int:
    return 600 + 160 * count


def _finding(q: Question, quote: str, why: str) -> Finding:
    return Finding(kind='contradiction', code=q.code, scene_quote=quote,
                   established_scene=q.established_scene,
                   established_quote=q.established_quote, fact_id=q.fact_id,
                   explanation=f'(question, asked {ASKINGS} times) The book has: '
                               f'"{q.statement}". {why}')


def _verified(answers: list[dict], n: int, prose: str) -> tuple[str, str]:
    """The first asking's (quote, why) whose quote is in the scene; ('', '')
    when none is."""
    return next(((a[n]['quote'], a[n]['why']) for a in answers
                 if a[n]['quote'] and quote_in(prose, a[n]['quote'])), ('', ''))


def ask_questions(scene_id: str, prose: str, questions: list[Question], *, model: str,
                  log_file: str = '') -> QuestionResult:
    """Ask `questions` (at most `MAX_QUESTIONS`; the rest are named in a
    note, a dispute among them unruled) twice each about `prose`. A finding
    needs two yeses and a quote in the scene (the first asking's when it is
    in the scene, else the second's, with that asking's reason). A
    dispute's question (`Question.dispute`) is ruled every time: two yeses
    with a verified quote are a finding, two noes clear it, anything else
    (split, misquoted, past the cap) leaves it unruled.

    Raises:
        QuestionError: a refusal, an API failure, or a reply cut off or off
            the schema twice running.
    """
    result = QuestionResult(scene_id)
    if len(questions) > MAX_QUESTIONS:
        over = questions[MAX_QUESTIONS:]
        result.notes.append(f'{len(over)} question(s) past the {MAX_QUESTIONS} a scene gets: '
                            f'not asked: {", ".join(q.fact_id for q in over)}')
        result.unruled += [q.dispute for q in over if q.dispute]
        questions = questions[:MAX_QUESTIONS]
    count = len(questions)
    answers = yes_no.ask(lambda n: build_prompt(scene_id, prose, questions, n), count,
                         model=model, log_file=log_file, tokens=max_tokens(count),
                         schema=SCHEMA, label=f'questions {scene_id}',
                         what=f'{scene_id}: the questions', error=QuestionError,
                         fields=('quote', 'why'))
    result.asked = count
    yes, split = yes_no.agreed(answers, count, 'yes')
    no, _ = yes_no.agreed(answers, count, 'no')
    misquoted = 0
    for n in yes:
        q = questions[n - 1]
        quote, why = _verified(answers, n, prose)
        if not quote:
            misquoted += 1
            continue
        result.findings.append(_finding(q, quote, why))
    found = {f.fact_id for f in result.findings}
    for n, q in enumerate(questions, start=1):
        if not q.dispute or q.fact_id in found:
            continue
        (result.cleared if n in no else result.unruled).append(q.dispute)
    result.split, result.misquoted = split, misquoted
    if split:
        result.notes.append(f'{split} question(s) got split answers: not findings')
    if misquoted:
        result.notes.append(f'{misquoted} question(s) answered yes twice with no quote in '
                            f'the scene: not findings')
    return result


# ============================================================================
# The brief's promises
# ============================================================================

def promises_for(brief) -> list[Promise]:
    """The promises to ask about from `brief` (`checker.brief_from`): each
    promise field's items and registry promises in words (`brief.items`),
    each binding registry fact it promises (`brief.promised`), and each
    planned fact (`brief.planned`), in that order."""
    from storyforge.must import strip_marker
    out = []
    for col, items_ in brief.items.items():
        for item in items_:
            text = ' '.join(strip_marker(item).split())
            if text:
                out.append(Promise('item', col, col, item, text))
    out += [Promise('promised', rid, '', ' '.join(st.split()), ' '.join(st.split()))
            for rid, st in brief.promised.items()]
    out += [Promise('planned', rid, '', ' '.join(st.split()), ' '.join(st.split()))
            for rid, st in brief.planned.items()]
    return out


_PROMISE_ASKS = {
    'item': 'The brief\'s {field}: "{text}"\n   Question: Does this scene deliver it?',
    'promised': 'The brief has the scene establish: "{text}"\n   Question: Does this scene '
                'establish it?',
    'planned': 'The brief plans (the scene may depart from it): "{text}"\n   Question: Does '
               'this scene establish it?',
}


def build_promise_prompt(scene_id: str, prose: str, promises: list[Promise],
                         asking: int = 1) -> str:
    """The promise questions, numbered from 1 in `promises`' order; a later
    asking reversed and labelled, as `build_prompt`'s."""
    blocks = ['{n}. ' + _PROMISE_ASKS[p.kind].format(field=p.field, text=p.text)
              for p in promises]
    return _independent(PROMISE_PROMPT.format(scene_id=scene_id, prose=prose.strip(),
                                              questions=_numbered(blocks, asking)), asking)


def _broken(p: Promise, why: str, problem: str = '') -> Finding:
    what = ('the scene does not deliver it' if not problem
            else f'not delivered for certain ({problem})')
    return Finding(kind='broken-promise', code=CODE_OF_TYPE['promise'], scene_quote='',
                   established_scene='', established_quote=p.raw, fact_id=p.fact_id,
                   explanation=f'(question, asked {ASKINGS} times) {what}'
                               + (f': {why}' if why else ''), problem=problem)


def ask_promises(scene_id: str, prose: str, promises: list[Promise], *, model: str,
                 log_file: str = '') -> QuestionResult:
    """Ask whether the scene delivers each of `promises` (at most
    `MAX_QUESTIONS`; the rest named in a note), twice each, in one call per
    asking. Two noes: a broken promise (`Finding`, kind `broken-promise`,
    the gate's to sort advisory or, for a `must:` beat, blocking), or for a
    planned fact a departure. Two yeses with a verified quote: delivered;
    a promised or planned fact's quote is `kept` (filled by the gate's
    commit) when it has `checker.MIN_KEPT_WORDS` words, else
    `kept_unverified`. Anything else (split, two yeses with no quote in the
    scene) is a note, and for a `must:` beat an unverified broken promise.

    Raises:
        QuestionError: as `ask_questions`.
    """
    from storyforge.checker import MIN_KEPT_WORDS
    from storyforge.quotes import word_count
    result = QuestionResult(scene_id)
    if len(promises) > MAX_QUESTIONS:
        over = promises[MAX_QUESTIONS:]
        result.notes.append(f'{len(over)} brief promise(s) past the {MAX_QUESTIONS} a scene '
                            f'gets: not asked: ' + '; '.join(p.text for p in over))
        result.unverified += [_broken(p, '', 'past the cap: not asked') for p in over
                              if p.must]
        promises = promises[:MAX_QUESTIONS]
    count = len(promises)
    answers = yes_no.ask(lambda n: build_promise_prompt(scene_id, prose, promises, n), count,
                         model=model, log_file=log_file, tokens=max_tokens(count),
                         schema=SCHEMA, label=f'promises {scene_id}',
                         what=f'{scene_id}: the promise questions', error=QuestionError,
                         fields=('quote', 'why'))
    result.promises_asked = count
    yes, split = yes_no.agreed(answers, count, 'yes')
    no, _ = yes_no.agreed(answers, count, 'no')
    unsure = []
    for n, p in enumerate(promises, start=1):
        if n in yes:
            quote, _why = _verified(answers, n, prose)
            if not quote:
                result.misquoted += 1
                unsure.append((p, 'yes twice, with no quote in the scene'))
            elif p.kind == 'item':
                pass
            elif word_count(quote) < MIN_KEPT_WORDS:
                result.kept_unverified.append((p.fact_id, quote,
                                               f'fewer than {MIN_KEPT_WORDS} words'))
            else:
                result.kept.append((p.fact_id, quote))
        elif n in no:
            why = answers[0][n]['why']
            if p.kind == 'planned':
                result.plan_departures.append(Finding(
                    'broken-promise', CODE_OF_TYPE['promise'], '', '', p.raw, p.fact_id,
                    f'(question) not established: {why}'))
            else:
                result.findings.append(_broken(p, why))
        else:
            unsure.append((p, 'split answers'))
    result.split = split
    for p, problem in unsure:
        if p.must:
            result.unverified.append(_broken(p, '', problem))
    if unsure:
        result.notes.append(f'{len(unsure)} brief promise(s) neither delivered nor broken by '
                            f'both askings (' + '; '.join(f'{p.fact_id}: {why}'
                                                         for p, why in unsure)
                            + '): not findings, but a must: beat among them blocks')
    return result


# ============================================================================
# The check
# ============================================================================

def check_questions(project_dir: str, scene_id: str, *, prose: str, rows: list[dict],
                    records, disputes: list[Dispute] | None = None,
                    model: str | None = None, log_file: str = '',
                    promises: bool = True) -> QuestionResult:
    """Ask `scene_id`'s prose about the facts in `rows` (the ledger as the
    gate reads it, without the scene's own commitments) that hold for it
    and whose subject is present by `records` (the scene's typed state),
    its places or its prose's names, or can't be placed; about the brief's
    entering items in words; about `disputes`; and, with `promises`, whether
    it delivers each of its brief's promises (`ask_promises`, its own call
    logged beside `log_file` as `-promises`). The notes say how many were
    asked and what wasn't.

    Raises:
        QuestionError: as `ask_questions`; or scenes.csv or a registry
            can't be read.
    """
    from storyforge import ledger
    from storyforge.checker import brief_from
    from storyforge.elaborate import _read_csv, _read_csv_as_map
    from storyforge.enrich import load_alias_map
    ref = os.path.join(project_dir, 'reference')
    try:
        order = ledger.scene_order(project_dir)
        subject_names, name_notes = ledger.subject_names(project_dir)
    except (ValueError, OSError, ledger.LedgerError) as e:
        raise QuestionError(f'{scene_id}: {e}') from e
    chars = load_alias_map(os.path.join(ref, 'characters.csv'))
    places = load_alias_map(os.path.join(ref, 'locations.csv'))
    location = (_read_csv_as_map(os.path.join(ref, 'scenes.csv')).get(scene_id, {})
                .get('location') or '')
    present = present_subjects(records, chars, places, location, prose=prose,
                               names=subject_names)
    names, registry = {}, set()
    for reg in ('characters.csv', 'locations.csv'):
        for r in _read_csv(os.path.join(ref, reg)):
            rid = (r.get('id') or '').strip()
            if rid:
                names[_norm(rid)] = (r.get('name') or rid).strip()
                registry.add(_norm(rid))
    picked = facts_to_ask(rows, scene_id, order, present, registry=registry, chars=chars,
                          places=places)
    by_id = {r.get('id'): r for r in rows}
    result = QuestionResult(scene_id, present=sorted(present))
    result.notes += [f'{n} (who is in the scene)' for n in name_notes]
    questions, ruled = [], set()
    for d in disputes or []:
        row = by_id.get(d.fact_id)
        if row is None or (row.get('type') or '').strip() not in CODE_OF_TYPE:
            result.unruled.append(d)
            result.notes.append(f'dispute on {d.fact_id}: no ledger fact of a known type to ask '
                                f'about: unruled')
            continue
        ruled.add(d.fact_id)
        questions.append(dispute_question(d, row, names.get(_norm(row.get('subject') or ''),
                                                            '')))
    # a disputed fact is asked once, as its dispute (one slip is not two)
    questions += [question_for(r, names.get(_lookup(r['subject'], chars, places),
                                            r['subject'].strip()), order)
                  for r in picked.facts if r['id'] not in ruled]
    brief = brief_from(rows, project_dir, scene_id)
    questions += [entering_question(col, item) for col, items_ in brief.entering.items()
                  for item in items_]
    if not present:
        result.notes.append('no one present by the typed state, no place, and no registry '
                            'name in the prose: only facts that can\'t be placed were asked')
    if picked.no_subject:
        result.notes.append(f'{len(picked.no_subject)} fact(s) with no subject, so their '
                            f'presence can\'t be told: not asked: '
                            + ', '.join(picked.no_subject))
    if picked.absent:
        result.notes.append(f'{len(picked.absent)} fact(s) about people or places not in the '
                            f'scene (by its typed state, its location, or a name in its '
                            f'prose): not asked')
    if questions:
        asked = ask_questions(scene_id, prose, questions, model=resolve_model(model),
                              log_file=log_file)
        asked.present, asked.notes = result.present, result.notes + asked.notes
        asked.unruled = result.unruled + asked.unruled
        result = asked
    if promises:
        result.unknown_brief_items = list(brief.unknown)
        result.stale_brief_items = list(brief.stale)
        wanted = promises_for(brief)
        if wanted:
            stem, ext = os.path.splitext(log_file)
            got = ask_promises(scene_id, prose, wanted, model=resolve_model(model),
                               log_file=f'{stem}-promises{ext}' if log_file else '')
            result.findings += got.findings
            result.unverified += got.unverified
            result.kept += got.kept
            result.kept_unverified += got.kept_unverified
            result.plan_departures += got.plan_departures
            result.promises_asked = got.promises_asked
            result.split += got.split
            result.misquoted += got.misquoted
            result.notes += got.notes
    result.notes.insert(0, f'{result.asked} question(s) about facts and disputes and '
                           f'{result.promises_asked} about brief promises asked, '
                           f'{len(present)} subject(s) present')
    return result
