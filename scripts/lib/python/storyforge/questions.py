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

- **Which facts** (`facts_to_ask`): binding ledger rows of `QUESTION_TYPES`
  (a `physical` row only outside `TYPED_CATEGORIES`, which the injury and
  possession checks compare) that hold for the scene: a fixed fact from any
  other scene or from before the book, a `state` fact only while it is in
  force entering the scene (`ledger.active_states`). Knowledge, timeline and
  promise rows are not asked: the knowledge and time checks compare the
  first two, and a brief's promises are the open checker's (advisory, #642).
- **Only about who is there** (`present_subjects`): a fact is asked only
  when its subject is present, by the scene's extracted cast (its typed
  state's `at` records, through the character registry) or its place (its
  scenes.csv `location`, or a place an `at` record names). So the number of
  questions scales with the scene, not the ledger. A fact with no subject
  can't be placed and is counted in the notes.
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
  `checker.Dispute`) are asked the same way: two yeses with a verified
  quote are a contradiction, two noes clear it, anything else leaves it
  unruled, which blocks the commit as the open checker's does.

Findings are `checker.Finding`s, contradictions with the code of the fact's
type (TRT, REL, PHY, WLD), set against the fact's scene and quote (the
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

#: The ledger types asked about: those whose content no typed check compares
QUESTION_TYPES = ('trait', 'relationship', 'physical', 'world')
#: `physical` categories the typed checks compare (the injury check; the
#: possession check): not asked
TYPED_CATEGORIES = ('injury', 'equipment')
#: Overrides the model (default the extraction tier)
MODEL_ENV = 'STORYFORGE_QUESTIONS_MODEL'
ASKINGS = yes_no.ASKINGS
#: The most questions asked per scene, disputes first (the rest are counted
#: in the notes; a dispute past it is unruled)
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


class QuestionError(RuntimeError):
    """The questions could not be asked; the message says why."""


@dataclass
class Question:
    fact_id: str
    #: the fact's ledger type (its finding's code is `CODE_OF_TYPE[type]`)
    type: str
    subject: str
    statement: str
    #: the scene that established it ('' for the ledger: before the book,
    #: or no scene)
    established_scene: str
    established_quote: str
    text: str
    #: a dispute: what extraction read in the scene ('' otherwise)
    claim: str = ''

    @property
    def code(self) -> str:
        return CODE_OF_TYPE.get(self.type, 'PHY')


@dataclass
class QuestionResult:
    scene_id: str
    findings: list[Finding] = field(default_factory=list)
    #: what couldn't be asked or answered, and why (never silent)
    notes: list[str] = field(default_factory=list)
    asked: int = 0
    #: questions with split answers, and with two yeses but no quote in the
    #: scene (each also a note)
    split: int = 0
    misquoted: int = 0
    #: disputes both askings said the scene doesn't contradict
    cleared: list[Dispute] = field(default_factory=list)
    #: disputes with no ruling (split, misquoted, past the cap): they block
    unruled: list[Dispute] = field(default_factory=list)
    #: the subjects found present (normalized ids), for the log
    present: list[str] = field(default_factory=list)


# ============================================================================
# Which facts, about whom
# ============================================================================

def _norm(text: str) -> str:
    from storyforge.ledger import _norm as ledger_norm
    return ledger_norm(text)


def present_subjects(records, chars: dict[str, str], places: dict[str, str],
                     location: str = '') -> set[str]:
    """The subjects present in the scene, normalized (`ledger._norm`): each
    `at` record's person (a registry id through `chars`, a lower-case name
    or alias → id; else the name itself), each place an `at` record names
    that `places` knows, and the scene's own `location`."""
    out = set()
    for r in records or []:
        if getattr(r, 'type', '') != 'at':
            continue
        who = ' '.join((r.who or '').split()).lower()
        if who:
            out.add(_norm(chars.get(who, who)))
        where = ' '.join((r.item or '').split()).lower()
        if where and (where in places or where.removeprefix('the ') in places):
            out.add(_norm(places.get(where) or places[where.removeprefix('the ')]))
    loc = ' '.join((location or '').split()).lower()
    if loc:
        out.add(_norm(places.get(loc, loc)))
    return out - {''}


def _asked_type(row: dict) -> bool:
    type_ = (row.get('type') or '').strip()
    if type_ not in QUESTION_TYPES:
        return False
    return not (type_ == 'physical'
                and (row.get('category') or '').strip().lower() in TYPED_CATEGORIES)


def facts_to_ask(rows: list[dict], scene_id: str, order: dict[str, int],
                 present: set[str]) -> tuple[list[dict], int]:
    """The ledger facts to ask `scene_id` about, in type order then reading
    order, and how many of the asked types that hold for the scene have no
    subject (they can't be placed, so aren't asked). A fact holds for the
    scene when it is binding and not the scene's own: a fixed one (or one
    with no `mutable`) from any other scene or none, unless a binding fact
    supersedes it; a `state` one while in force entering the scene."""
    from storyforge.ledger import active_states
    candidates = [r for r in rows if (r.get('status') or '') == 'binding' and _asked_type(r)
                  and (r.get('scene_id') or '').strip() != scene_id]
    superseded = {old.strip() for r in rows if (r.get('status') or '') == 'binding'
                  for old in (r.get('supersedes') or '').split(';') if old.strip()}
    in_force = {r['id'] for r in active_states(rows, scene_id, order, entering=True)} \
        if scene_id in order else set()
    holding = [r for r in candidates
               if (r['id'] in in_force if (r.get('mutable') or '') == 'state'
                   else r['id'] not in superseded)]
    no_subject = sum(1 for r in holding if not (r.get('subject') or '').strip())
    asked = [r for r in holding if _norm(r.get('subject') or '') in present
             and (r.get('subject') or '').strip()]
    rank = {t: n for n, t in enumerate(QUESTION_TYPES)}

    def where(r: dict) -> int:
        return order.get((r.get('scene_id') or '').strip(), -1)
    return sorted(asked, key=lambda r: (rank[r['type'].strip()], where(r), r['id'])), no_subject


_ASKS = {
    'trait': 'Does this scene show or say something about {name} that this fact rules out?',
    'relationship': 'Does this scene show or say something about {name} and the others '
                    'this fact names that it rules out?',
    'physical': 'Does this scene describe {name} or what {name} has or can do in a way this '
                'fact rules out?',
    'world': 'Does this scene show {name} or how the world works in a way this fact rules '
             'out?',
}


def question_for(row: dict, name: str, order: dict[str, int] | None = None) -> Question:
    """The question for one ledger fact, written by code from its type,
    subject (`name`, as the book names it) and statement. Its established
    scene is the fact's scene when that is a scene of the book (`order`;
    None: any), else '' (the ledger)."""
    scene = (row.get('scene_id') or '').strip()
    if order is not None and scene not in order:
        scene = ''
    statement = ' '.join((row.get('statement') or '').split())
    quote = ' '.join((row.get('quote') or '').split()) if scene else ''
    type_ = (row.get('type') or '').strip()
    return Question(fact_id=row.get('id', ''), type=type_, subject=name, statement=statement,
                    established_scene=scene, established_quote=quote or statement,
                    text=_ASKS.get(type_, _ASKS['trait']).format(name=name))


def dispute_question(d: Dispute, row: dict | None, name: str = '') -> Question:
    """The question for a dispute: extraction read the scene as changing a
    registry fact; does it contradict it?"""
    row = row or {}
    scene = (row.get('scene_id') or '').strip()
    return Question(fact_id=d.fact_id, type=(row.get('type') or '').strip(),
                    subject=name or (row.get('subject') or '').strip(),
                    statement=' '.join(d.statement.split()), established_scene=scene,
                    established_quote=' '.join((row.get('quote') or '').split())
                    or ' '.join(d.statement.split()),
                    text=f'A reader took this scene to change the fact: "{" ".join(d.claim.split())}". '
                         f'Does the scene contradict the fact, so that it no longer holds as '
                         f'stated?',
                    claim=d.claim)


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


def build_prompt(scene_id: str, prose: str, questions: list[Question], asking: int = 1) -> str:
    """The questions, numbered from 1 in `questions`' order. A later asking
    lists them in reverse and says which it is (`yes_no`)."""
    order = list(enumerate(questions, start=1))
    if asking > 1:
        order.reverse()
    text = PROMPT.format(scene_id=scene_id, prose=prose.strip(),
                         questions='\n\n'.join(_block(n, q) for n, q in order))
    if asking > 1:
        text += f'\n\nThis is independent asking {asking}: answer each question afresh.'
    return text


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


def ask_questions(scene_id: str, prose: str, questions: list[Question], *, model: str,
                  log_file: str = '', disputes: dict[str, Dispute] | None = None
                  ) -> QuestionResult:
    """Ask `questions` (at most `MAX_QUESTIONS`; the rest are noted, a
    dispute among them unruled) twice each about `prose`. A finding needs
    two yeses and a quote in the scene (the first asking's when it is in
    the scene, else the second's). `disputes`: fact id → the dispute a
    question asks about (its own rule: two noes clear it; anything but a
    finding or that leaves it unruled).

    Raises:
        QuestionError: a refusal, an API failure, or a reply cut off or off
            the schema twice running.
    """
    disputes = disputes or {}
    result = QuestionResult(scene_id)
    if len(questions) > MAX_QUESTIONS:
        over = questions[MAX_QUESTIONS:]
        result.notes.append(f'{len(over)} question(s) past the {MAX_QUESTIONS} a scene gets: '
                            f'not asked')
        result.unruled += [disputes[q.fact_id] for q in over
                           if q.claim and q.fact_id in disputes]
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
        quote = next((a[n]['quote'] for a in answers
                      if a[n]['quote'] and quote_in(prose, a[n]['quote'])), '')
        if not quote:
            misquoted += 1
            if q.claim and q.fact_id in disputes:
                result.unruled.append(disputes[q.fact_id])
            continue
        result.findings.append(_finding(q, quote, answers[0][n]['why']))
    for n in range(1, count + 1):
        q = questions[n - 1]
        if not (q.claim and q.fact_id in disputes) or n in yes:
            continue
        (result.cleared if n in no else result.unruled).append(disputes[q.fact_id])
    result.split, result.misquoted = split, misquoted
    if split:
        result.notes.append(f'{split} question(s) got split answers: not findings')
    if misquoted:
        result.notes.append(f'{misquoted} question(s) answered yes twice with no quote in '
                            f'the scene: not findings')
    return result


# ============================================================================
# The check
# ============================================================================

def check_questions(project_dir: str, scene_id: str, *, prose: str, rows: list[dict],
                    records, disputes: list[Dispute] | None = None,
                    model: str | None = None, log_file: str = '') -> QuestionResult:
    """Ask `scene_id`'s prose about the facts in `rows` (the ledger as the
    gate reads it, without the scene's own commitments) whose subject is
    present by `records` (the scene's typed state) or its place, and about
    `disputes`.

    Raises:
        QuestionError: as `ask_questions`; or scenes.csv can't be read.
    """
    from storyforge import ledger
    from storyforge.elaborate import _read_csv, _read_csv_as_map
    from storyforge.enrich import load_alias_map
    ref = os.path.join(project_dir, 'reference')
    try:
        order = ledger.scene_order(project_dir)
    except (ValueError, OSError, ledger.LedgerError) as e:
        raise QuestionError(f'{scene_id}: {e}') from e
    chars = load_alias_map(os.path.join(ref, 'characters.csv'))
    places = load_alias_map(os.path.join(ref, 'locations.csv'))
    location = (_read_csv_as_map(os.path.join(ref, 'scenes.csv')).get(scene_id, {})
                .get('location') or '')
    present = present_subjects(records, chars, places, location)
    names = {}
    for registry in ('characters.csv', 'locations.csv'):
        for r in _read_csv(os.path.join(ref, registry)):
            rid = (r.get('id') or '').strip()
            if rid:
                names[_norm(rid)] = (r.get('name') or rid).strip()
    facts, no_subject = facts_to_ask(rows, scene_id, order, present)
    by_id = {r.get('id'): r for r in rows}
    questions = [dispute_question(d, by_id.get(d.fact_id),
                                  names.get(_norm((by_id.get(d.fact_id) or {}).get('subject')
                                                  or ''), ''))
                 for d in disputes or []]
    questions += [question_for(r, names.get(_norm(r['subject']), r['subject'].strip()), order)
                  for r in facts]
    result = QuestionResult(scene_id, present=sorted(present))
    if not present:
        result.notes.append('no one present by the typed state, and no place: no ledger fact '
                            'was asked about')
    if no_subject:
        result.notes.append(f'{no_subject} fact(s) of the asked types have no subject, so '
                            f'their presence can\'t be told: not asked')
    if questions:
        asked = ask_questions(scene_id, prose, questions, model=resolve_model(model),
                              log_file=log_file, disputes={d.fact_id: d for d in disputes or []})
        asked.present, asked.notes = result.present, result.notes + asked.notes
        result = asked
    return result
