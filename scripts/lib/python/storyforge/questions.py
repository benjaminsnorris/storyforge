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
  `physical` row is asked). A `state` trait (a mood, attire, a posture)
  set on an earlier `timeline_day` may be stale: it is asked last (#739).
- **Likeliest slips first** (#739): disputes, the brief's entering items,
  then the facts: the on-stage cast's physical states, then the last
  `RECENT_SCENES` scenes' facts, then the rest, each by `TYPE_SALIENCE`
  and the nearest scene. At most `MAX_QUESTIONS` (30), asked `BATCH` (30)
  to a call; the cap cuts from the end.
- **Only about who is there** (`present_subjects`): a fact is asked when
  its subject (an id, name or alias, through the registries) is present by
  the scene's extracted cast (its typed state's `at` records), its places
  (its scenes.csv `location`s, or a place an `at` record names) or a
  registry name its prose uses (someone only talked about, remembered or
  dead). A subject in no registry (a group, a concept) can't be placed, so
  its facts are asked in every scene; a fact with no subject, or about a
  registry entry the scene doesn't have, isn't asked, and the notes count
  both. So the number of questions scales with the scene, not the ledger.
  A name several subjects share places only those the brief's cast, a
  recent fact or a name only one has ties to the scene (#746, `presence`).
- **Storyforge writes the questions** (`question_for`), from the fact's
  type, subject and statement; no model writes them.
- **Each is asked twice** (`yes_no.ask`, the stage sheet's machinery, #647):
  all of a scene's questions in one call per asking, the second in reverse
  order, on the smallest model that holds the question set's floors
  (`resolve_model`: `STORYFORGE_QUESTIONS_MODEL`, else the extraction tier).
  A finding needs two `yes` answers **and** a quote that verifies
  (`quotes.quote_in`). The questions the two askings split on are asked a
  third time, alone (`TIE_ASKING`), so two yeses of three are a finding
  (2026-11-16: three of the question set's 17 cases were splits). Two
  yeses with no quote in the scene are a note, never a finding.
- **Disputes** (registry facts extraction says the scene changes,
  `checker.Dispute`) are asked the same way, each fact once (a disputed
  fact isn't also asked plainly), with the doubt leaning the other way:
  two yeses with a verified quote are a contradiction (a split broken by
  the third asking included), two noes from the first two askings clear it
  (a third no doesn't: clearing one lifts a block), anything else leaves it
  unruled, which blocks the commit as the open checker's does.
- **The brief's promises** (`promises_for`, `ask_promises`) are their own
  call, asked twice, with no third asking (a split is unsure, as before): does the scene deliver each item of its brief? Two
  noes are a broken promise (advisory, unless a `must:` beat, #642), two
  yeses with a verified quote deliver it and fill a promised registry
  fact's blank quote (`kept`, as the open checker's), and anything else is a
  note, or for a `must:` beat an unverified broken promise, which blocks.
  The brief's entering items written in words are asked as facts. A
  promised physical state an earlier scene set that is still in force
  entering the scene isn't asked as this scene's to establish
  (`held_entering`), nor is an `outcome` that is only "yes" or "no"; the
  notes name both (#740).

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
import re
from dataclasses import dataclass, field

from storyforge import yes_no
from storyforge.checker import CODE_OF_TYPE, Dispute, Finding
from storyforge.quotes import quote_in

#: The ledger types asked about: every type but `promise` (a set-up the
#: story pays off, not a fact a scene contradicts). Within them, a fact a
#: typed check compares by code (`continuity.covered_fact_ids`, the one
#: source: knowledge facts someone knows) is not asked
QUESTION_TYPES = ('trait', 'relationship', 'physical', 'world', 'knowledge', 'timeline')
#: #739: within a tier of `facts_to_ask`'s order, the types most likely
#: to be contradicted first. On *Wrath Like Smoke* (2026-11-17) the old
#: order, trait first, asked 889 of 936 qualifying traits and 192 of 2,246
#: physical facts, where the open checker's real catches were 27 of 50
#: timeline and 11 physical
TYPE_SALIENCE = ('physical', 'timeline', 'relationship', 'world', 'knowledge', 'trait')
#: #739: the scenes just before this one whose facts are asked next after
#: the on-stage cast's physical states; also how far back a fact ties a
#: shared name's bearer to the scene (#746)
RECENT_SCENES = 5
#: Overrides the model (default the extraction tier)
MODEL_ENV = 'STORYFORGE_QUESTIONS_MODEL'
ASKINGS = yes_no.ASKINGS
#: The most questions asked per scene, disputes first (the rest are named
#: in the notes; a dispute past it is unruled), asked in calls of `BATCH`.
#: #739 put the likeliest slips first and tried 60 (two calls): on
#: `gate-set-questions` (2026-11-26) 60 had the same run-1 recall, one more
#: catch in run 2, and one more false alarm on a correct fact over three
#: runs (8 to 7), so it stays 30 (docs/history.md). The brief's promises are their own call with
#: their own cap (`MAX_PROMISES`)
MAX_QUESTIONS = 30
#: Questions per call: a scene's questions past it are a second call (each
#: asked twice, its splits a third time, as the first)
BATCH = 30
#: The most brief promises asked per scene (one call)
MAX_PROMISES = 30
#: The number of the asking that breaks a split (an asking's number names
#: its log, `.a3`, and its prompt, "independent asking 3"): only the split
#: questions, one more call. "Two yeses of three" holds only for two
#: askings before it, so a change to `ASKINGS` must rethink the rule
TIE_ASKING = ASKINGS + 1
assert ASKINGS == 2, 'the tie-break is two yeses of three: rethink it for other ASKINGS'

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

Answer `yes` when any clause of the scene shows or says something that cannot be true if the fact holds, and put in `quote` that clause, copied exactly: the shortest clause that shows it. Check every clause: words elsewhere in the scene that agree with the fact don't cancel one that contradicts it, since the error may be in one sentence only. Dialogue and a character's memory count as the book's word: a character who gives a wrong name, a wrong kinship, a wrong place or a wrong past is a contradiction, unless the scene itself shows that it is wrong (another character corrects it, the narration says it's a lie, a joke or a slip). A description counts as what it says, not as a mere look.

Answer `no` when the scene agrees with the fact or says nothing about it, when the words are plainly a figure of speech, or are a dream, a vision or something imagined, or when the scene itself shows the fact changing. Give a one-sentence reason in `why`; with `no`, `quote` is empty.

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
    #: the ending this question rules on (#734; `ending_question`): two
    #: yeses with a quote in the scene from the first two askings say the
    #: scene shows the state ending; never a finding
    ending: Dispute | None = None

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
    #: of `facts`, in-force `state` traits (a mood, what someone wears, a
    #: posture, but also a vow or a grudge) set on an earlier
    #: `timeline_day` than the scene's: maybe stale, so asked last (#739)
    stale: list[str] = field(default_factory=list)


@dataclass
class QuestionResult:
    scene_id: str
    findings: list[Finding] = field(default_factory=list)
    #: what couldn't be asked or answered, and why (never silent)
    notes: list[str] = field(default_factory=list)
    #: fact and dispute questions asked (each `ASKINGS` times, a split one
    #: a third time)
    asked: int = 0
    #: the ledger fact ids those questions were about, in asking order (an
    #: entering item's is its brief field): what was actually put to the
    #: model, for an eval that seeds a fact to tell "asked and missed" from
    #: "never asked" (#677)
    asked_fact_ids: list[str] = field(default_factory=list)
    #: fact and dispute questions the first two askings split on (a note),
    #: each asked a third time (`TIE_ASKING`)
    split: int = 0
    #: findings made by the third asking: split, then yes with a quote in
    #: the scene (two yeses of three)
    tie_found: int = 0
    #: brief promises the two askings split on (never asked again: unsure)
    promise_split: int = 0
    #: questions answered yes twice with no quote in the scene (a note)
    misquoted: int = 0
    #: disputes the first two askings both said the scene doesn't contradict
    cleared: list[Dispute] = field(default_factory=list)
    #: disputes with no ruling (split then no, misquoted, past the cap, no
    #: fact to ask about): they block
    unruled: list[Dispute] = field(default_factory=list)
    #: endings (#734) the first two askings both said the scene shows, with
    #: a quote in the scene
    ended: list[Dispute] = field(default_factory=list)
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


@dataclass
class Presence:
    """Who and what is in the scene (`presence`), normalized ids."""
    #: present: asked about
    present: set[str] = field(default_factory=set)
    #: of `present`, the people the typed state puts there (`at` records):
    #: their physical states are asked first (#739)
    on_stage: set[str] = field(default_factory=set)
    #: a shared name whose bearers weren't all placed, and why (#746)
    notes: list[str] = field(default_factory=list)


def present_subjects(records, chars: dict[str, str], places: dict[str, str],
                     location: str = '', *, prose: str = '',
                     names: dict[str, set[str]] | None = None,
                     tied: set[str] | frozenset = frozenset()) -> set[str]:
    """`presence(...).present`."""
    return presence(records, chars, places, location, prose=prose, names=names,
                    tied=tied).present


def presence(records, chars: dict[str, str], places: dict[str, str],
             location: str = '', *, prose: str = '',
             names: dict[str, set[str]] | None = None,
             tied: set[str] | frozenset = frozenset()) -> Presence:
    """The subjects present in the scene, normalized (`ledger._norm`): each
    `at` record's person (a registry id through `chars`, a lower-case name
    or alias → id; else the name itself), each place an `at` record names
    that `places` knows, each of the scene's own `location`s (scenes.csv's
    `;` array), and each registry subject its `prose` names as a whole word
    (`names`: `ledger.subject_names`, id → its names and aliases), so a
    character only talked about, remembered or dead is asked about too.

    A name `names` gives two or more subjects (#746: Homer's two Ajaxes,
    several Pisanders; `ledger.name_index`) places only those of them that
    something else ties to the scene: `tied` (normalized ids: the brief's
    cast, the subjects of the last few scenes' facts) or a name only that
    one has in the prose ("son of Oileus"). An `at` record or the prose
    naming one with nothing tying any of them places none, and the notes
    say so: a bare "Pisander" used to mark every Pisander present, and a
    fact about the wrong man was asked."""
    from storyforge.ledger import _norm as norm
    from storyforge.ledger import _phrases, name_index, named_by, phrase_pattern
    out = Presence()
    names = names or {}
    index = name_index(names)
    shared = {p: ids for p, ids in index.items() if len(ids) > 1}
    text = norm(prose) if prose else ''
    # a subject the prose names by a phrase no other subject has
    own: set[str] = set()
    if text:
        for sid in names:
            pattern = phrase_pattern(_phrases(sid, names) - shared.keys())
            if pattern and pattern.search(text):
                own.add(sid)
    ties = set(tied) | own
    held: dict[str, tuple[set[str], str]] = {}

    def namesakes(phrase: str, ids: set[str], where: str) -> set[str]:
        placed = ids & ties
        if ids - placed - own:
            held.setdefault(phrase, (ids, where))
        return placed

    for r in records or []:
        if getattr(r, 'type', '') != 'at':
            continue
        who = ' '.join((r.who or '').split())
        if who:
            ids = named_by(who, index)
            if len(ids) > 1:
                placed = namesakes(norm(who).removeprefix('the '), ids, 'the typed state')
                out.present |= placed
                out.on_stage |= placed
            else:
                key = _lookup(who, chars)
                out.present.add(key)
                out.on_stage.add(key)
        where = ' '.join((r.item or '').split()).lower()
        if where and (where in places or where.removeprefix('the ') in places):
            out.present.add(_lookup(where, places))
    for loc in (location or '').split(';'):
        if loc.strip():
            out.present.add(_lookup(loc, places))
    if text:
        out.present |= own
        for phrase, ids in shared.items():
            pattern = phrase_pattern([phrase])
            if pattern and pattern.search(text):
                out.present |= namesakes(phrase, ids, 'the prose')
    for phrase, (ids, where) in sorted(held.items()):
        placed = sorted(ids & out.present)
        left = sorted(ids - out.present)
        if not left:
            continue
        out.notes.append(
            f'"{phrase}" in {where} names {len(ids)} people ({", ".join(sorted(ids))}): '
            + (f'placed {", ".join(placed)}, tied to the scene by its cast, a recent fact or '
               f'a name only they have; not ' if placed else
               'none is tied to the scene by its cast, a recent fact or a name only one has, '
               'so none is ')
            + f'placed: {", ".join(left)}')
    out.present -= {''}
    out.on_stage -= {''}
    return out


def tied_subjects(cast: list[str], rows: list[dict], scene_id: str, order: dict[str, int],
                  names: dict[str, set[str]]) -> set[str]:
    """The subjects tied to `scene_id` other than by a name in its prose
    (#746), normalized ids: each of the brief's `cast` (ids or names; a name
    two people share ties neither) and the subject of each binding fact of
    the `RECENT_SCENES` scenes before it (by id or a name only it has)."""
    from storyforge.ledger import name_index, named_by
    index = name_index(names)

    def one(name: str) -> set[str]:
        ids = named_by(name, index)
        return ids if len(ids) == 1 else set()
    out: set[str] = set()
    for name in cast:
        out |= one(name)
    at = order.get(scene_id)
    if at is not None:
        for r in rows:
            pos = order.get((r.get('scene_id') or '').strip())
            if (r.get('status') or '') == 'binding' and pos is not None \
                    and at - RECENT_SCENES <= pos < at:
                out |= one((r.get('subject') or '').strip())
    return out


def facts_to_ask(rows: list[dict], scene_id: str, order: dict[str, int],
                 present: set[str], *, registry: set[str] | frozenset = frozenset(),
                 chars: dict[str, str] | None = None,
                 places: dict[str, str] | None = None,
                 on_stage: set[str] | frozenset = frozenset(),
                 days: dict[str, int] | None = None) -> Selection:
    """The ledger facts to ask `scene_id` about, likeliest slips first
    (the cap cuts from the end), and what was left out. A fact holds for
    the scene when it is binding, of `QUESTION_TYPES`, no typed check
    compares it (`continuity.covered_fact_ids`) and it is not the scene's
    own: a fixed one (or one with no `mutable`) from any other scene or
    none, unless a binding fact supersedes it; a `state` one while in force
    entering the scene. A holding fact is asked when its subject
    (through `chars` and `places`, the registries' alias maps) is
    `present`, or is in no `registry` (normalized registry ids: a group or
    concept can't be placed, so it's asked everywhere); with no subject, or
    about a registry entry the scene doesn't have, it isn't.

    The order (#739): first the in-force physical states of the on-stage
    cast (`on_stage`, normalized ids: the typed state's `at` records), what
    they hold or wear, their wounds, where they are; then facts from the
    `RECENT_SCENES` scenes before this one; then the rest. Within each, an
    on-stage subject's first, then by `TYPE_SALIENCE`, then the nearest
    scene first (a fact from no scene of the book last), then by id. Last
    of all, a `state` trait set on an earlier `timeline_day` (`days`, scene
    → day; `Selection.stale`): a mood or what someone wore is likely over,
    but a vow or a grudge isn't, and nothing tells them apart, so they are
    asked when the cap leaves room."""
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
    days = days or {}
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
    stale = {r['id'] for r in asked if _stale(r, scene_id, days)}
    rank = {t: n for n, t in enumerate(TYPE_SALIENCE)}
    at = order.get(scene_id)

    def key(r: dict) -> tuple:
        type_ = r['type'].strip()
        here = _lookup((r.get('subject') or '').strip(), chars or {}, places or {}) in on_stage
        pos = order.get((r.get('scene_id') or '').strip())
        if r['id'] in stale:
            tier = 3
        elif here and type_ == 'physical' and (r.get('mutable') or '') == 'state':
            tier = 0
        elif at is not None and pos is not None and at - RECENT_SCENES <= pos < at:
            tier = 1
        else:
            tier = 2
        distance = abs(at - pos) if at is not None and pos is not None else len(order) + 1
        return (tier, not here, rank[type_], distance, r['id'])
    out.facts = sorted(asked, key=key)
    out.stale = [r['id'] for r in out.facts if r['id'] in stale]
    return out


def scene_days(scenes: dict[str, dict]) -> dict[str, int]:
    """Scene id → its scenes.csv `timeline_day`, for each scene whose day is
    a whole number (a scene with none, or another kind, can't tell a day
    boundary)."""
    out = {}
    for sid, r in scenes.items():
        try:
            out[sid] = int((r.get('timeline_day') or '').strip())
        except ValueError:
            continue
    return out


def _stale(r: dict, scene_id: str, days: dict[str, int]) -> bool:
    """Whether `r` is a `state` trait set on an earlier `timeline_day`
    than `scene_id`'s: a mood, attire or a posture past a day boundary
    likely no longer holds, though nothing in the ledger ended it (#739:
    two of the question checker's four false fact findings on *Wrath Like
    Smoke*); a vow or a grudge still does. A day not known for either scene
    can't tell."""
    if (r.get('type') or '').strip() != 'trait' or (r.get('mutable') or '') != 'state':
        return False
    now, then = days.get(scene_id), days.get((r.get('scene_id') or '').strip())
    return now is not None and then is not None and now > then


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


def _finding(q: Question, quote: str, why: str, tie_break: bool = False) -> Finding:
    asked = (f'asked {TIE_ASKING} times, split, then yes' if tie_break
             else f'asked {ASKINGS} times')
    return Finding(kind='contradiction', code=q.code, scene_quote=quote,
                   established_scene=q.established_scene,
                   established_quote=q.established_quote, fact_id=q.fact_id,
                   explanation=f'(question, {asked}) The book has: "{q.statement}". {why}')


def _verified(said: list[dict[str, str]], prose: str) -> tuple[str, str]:
    """Of one question's answers (`said`, in asking order), the first
    (quote, why) whose quote is in the scene; ('', '') when none is."""
    return next(((a['quote'], a['why']) for a in said
                 if a['quote'] and quote_in(prose, a['quote'])), ('', ''))


def batch_log(log_file: str, batch: int) -> str:
    """Where batch `batch` of a scene's questions logs: `log_file` for the
    first, `-b<n>` before its extension for a later one ('' when there is
    no log); each asking's own log is beside it (`yes_no.asking_log`)."""
    if batch == 1 or not log_file:
        return log_file
    stem, ext = os.path.splitext(log_file)
    return f'{stem}-b{batch}{ext}'


def ask_questions(scene_id: str, prose: str, questions: list[Question], *, model: str,
                  log_file: str = '') -> QuestionResult:
    """Ask `questions` (at most `MAX_QUESTIONS`; the rest are named in a
    note, a dispute among them unruled) twice each about `prose`, `BATCH`
    to a call (the batches at once, a later one logged at `batch_log`). A
    finding needs two yeses and a quote in the scene, from an asking that
    said yes (the first such whose quote is in the scene, with its reason).
    A question the two askings split on is asked a third time, alone with
    the other split ones of its batch (`TIE_ASKING`): a yes there is the
    second yes. A dispute's question (`Question.dispute`) is ruled every
    time: two yeses with a verified quote are a finding, two noes from the
    first two askings clear it, anything else (split then no, misquoted,
    past the cap) leaves it unruled.

    Raises:
        QuestionError: a refusal, an API failure, or a reply cut off or off
            the schema twice running.
    """
    from storyforge.runner import together
    result = QuestionResult(scene_id)
    if len(questions) > MAX_QUESTIONS:
        over = questions[MAX_QUESTIONS:]
        result.notes.append(f'{len(over)} question(s) past the {MAX_QUESTIONS} a scene gets: '
                            f'not asked: {", ".join(q.fact_id for q in over)}')
        result.unruled += [q.dispute for q in over if q.dispute]
        questions = questions[:MAX_QUESTIONS]
    batches = [questions[i:i + BATCH] for i in range(0, len(questions), BATCH)] or [[]]
    parts = together(*(
        (lambda b=b, k=k: _ask_batch(scene_id, prose, b, model, batch_log(log_file, k)))
        for k, b in enumerate(batches, start=1)))
    for k, part in enumerate(parts, start=1):
        result.findings += part.findings
        result.asked += part.asked
        result.asked_fact_ids += part.asked_fact_ids
        result.split += part.split
        result.tie_found += part.tie_found
        result.misquoted += part.misquoted
        result.cleared += part.cleared
        result.unruled += part.unruled
        result.ended += part.ended
        result.notes += [f'batch {k} of {len(parts)}: {n}' if len(parts) > 1 else n
                         for n in part.notes]
    return result


def _ask_batch(scene_id: str, prose: str, questions: list[Question], model: str,
               log_file: str) -> QuestionResult:
    """`ask_questions` for one call's questions (at most `BATCH`)."""
    result = QuestionResult(scene_id)
    count = len(questions)
    answers = yes_no.ask(lambda n: build_prompt(scene_id, prose, questions, n), count,
                         model=model, log_file=log_file, tokens=max_tokens(count),
                         schema=SCHEMA, label=f'questions {scene_id}',
                         what=f'{scene_id}: the questions', error=QuestionError,
                         fields=('quote', 'why'))
    result.asked = count
    result.asked_fact_ids = [q.fact_id for q in questions]
    agreed_yes, split = yes_no.agreed(answers, count, 'yes')
    no, _ = yes_no.agreed(answers, count, 'no')
    # each yes question's answers that said yes, in asking order (`_verified`)
    said_yes = {n: [a[n] for a in answers] for n in agreed_yes}
    tied = [n for n in range(1, count + 1) if n not in agreed_yes and n not in no]
    tie_yes: set[int] = set()
    tie_no: list[int] = []
    if tied:
        # a split is broken by a third asking of just those questions: two
        # yeses of three are a finding. A dispute is still cleared only by
        # the first two saying no: a third no leaves it unruled
        sub = [questions[n - 1] for n in tied]
        names = ', '.join(q.fact_id for q in sub)
        third = yes_no.structured_call(
            build_prompt(scene_id, prose, sub, TIE_ASKING), model,
            yes_no.asking_log(log_file, TIE_ASKING), max_tokens(len(sub)), SCHEMA,
            f'questions {scene_id} (tie)',
            lambda t: yes_no.parse_answers(t, len(sub), ('quote', 'why')),
            f'{scene_id}: the third asking of the split questions ({names}), after the '
            f'first two answered', QuestionError)
        for i, n in enumerate(tied, start=1):   # `third` is numbered as `sub`
            if third[i]['answer'] == 'yes':
                tie_yes.add(n)
                said_yes[n] = [a[n] for a in answers if a[n]['answer'] == 'yes'] + [third[i]]
            else:
                tie_no.append(n)
    misquoted = 0
    for n in sorted(said_yes):
        q = questions[n - 1]
        quote, why = _verified(said_yes[n], prose)
        if q.ending is not None:
            # #734: an ending is a yes of the first two askings with a quote
            # in the scene; a tie-break yes, or no quote, records nothing
            if quote and n in agreed_yes:
                result.ended.append(q.ending)
            continue
        if not quote:
            misquoted += 1
            continue
        result.findings.append(_finding(q, quote, why, tie_break=n in tie_yes))
        result.tie_found += n in tie_yes
    found = {f.fact_id for f in result.findings}
    for n, q in enumerate(questions, start=1):
        if not q.dispute or q.fact_id in found:
            continue
        (result.cleared if n in no else result.unruled).append(q.dispute)
    result.split, result.misquoted = split, misquoted
    if split:
        result.notes.append(
            f'{split} question(s) got split answers and were asked a third time: '
            f'{result.tie_found} found (two yeses of three, the quote in the scene): '
            + ', '.join(questions[n - 1].fact_id for n in tied))
    held = [questions[n - 1].fact_id for n in tie_no if questions[n - 1].dispute]
    if held:
        result.notes.append(
            f'{len(held)} dispute(s) split, then no on the third asking, left unruled: two '
            f'of three say the scene doesn\'t contradict it, but only the first two askings '
            f'both saying no clear one: ' + ', '.join(held))
    if misquoted:
        result.notes.append(f'{misquoted} question(s) answered yes twice with no quote in '
                            f'the scene: not findings')
    return result


def ending_question(d: Dispute, row: dict, name: str = '') -> Question:
    """#734: the question for a state the plan sets up in the scene that
    extraction read as ending there: does the scene show it ending? `yes`
    is the ending (never a finding), and the doubt goes to `no`: an end
    recorded on a misreading would take a true state out of the book."""
    scene = (row.get('scene_id') or '').strip()
    claim = ' '.join(d.claim.split())
    return Question(fact_id=d.fact_id, type=(row.get('type') or '').strip(),
                    subject=name or (row.get('subject') or '').strip(),
                    statement=' '.join(d.statement.split()), established_scene=scene,
                    established_quote=' '.join((row.get('quote') or '').split())
                    or ' '.join(d.statement.split()),
                    text=(f'A reader took this scene to end the fact: "{claim}". ' if claim
                          else 'A reader took this scene to end the fact. ')
                         + 'Does the scene clearly show this state ending, so that it no '
                           'longer holds after the scene? Answer `yes` only when it clearly '
                           'does, and quote the words that show it; if it doesn\'t, or you '
                           'can\'t tell, answer `no`.',
                    ending=d)


# ============================================================================
# The brief's promises
# ============================================================================

def promises_for(brief, *, entering: dict[str, str] | None = None,
                 fields: dict[str, str] | None = None,
                 left_out: list[str] | None = None) -> list[Promise]:
    """The promises to ask about from `brief` (`checker.brief_from`): each
    promise field's items and registry promises in words (`brief.items`),
    each binding registry fact it promises (`brief.promised`; its brief
    field from `fields`, id → field, `promised_fields`), and each planned
    fact (`brief.planned`), in that order.

    Not asked, each named in `left_out` (#740, *Wrath Like Smoke*: 7 of 9
    blocking promise findings false, none real, and two of them led fixes
    to write real errors): a promised fact in `entering` (id → why, from
    `held_entering`: a physical state an earlier scene set that is still in
    force entering this one, not this scene's to set up); and an `outcome`
    that is only "yes" or "no", which names no event to deliver."""
    from storyforge.must import strip_marker
    entering = entering or {}
    fields = fields or {}
    left_out = left_out if left_out is not None else []
    out = []
    for col, items_ in brief.items.items():
        for item in items_:
            text = ' '.join(strip_marker(item).split())
            if col == 'outcome' and bare_answer(text):
                left_out.append(f'{col}: "{text}" (only an answer: it names no event to '
                                f'deliver)')
                continue
            if text:
                out.append(Promise('item', col, col, item, text))
    for rid, st in brief.promised.items():
        if rid in entering:
            left_out.append(f'{fields.get(rid) or "promised"} {rid} ({entering[rid]})')
            continue
        out.append(Promise('promised', rid, fields.get(rid, ''), ' '.join(st.split()),
                           ' '.join(st.split())))
    out += [Promise('planned', rid, '', ' '.join(st.split()), ' '.join(st.split()))
            for rid, st in brief.planned.items()]
    return out


def promised_fields(rows: list[dict], ids) -> dict[str, str]:
    """The brief field each promised registry fact of `ids` came from, by
    its type (`checker.REGISTRY_PROMISE_FIELDS`: a physical fact is a
    `physical_state_out`, a knowledge fact a `knowledge_out`)."""
    from storyforge.checker import REGISTRY_PROMISE_FIELDS
    field_of = {t: col for col, t in REGISTRY_PROMISE_FIELDS.items()}
    wanted = set(ids)
    return {r['id']: field_of[(r.get('type') or '').strip()] for r in rows
            if r.get('id') in wanted and (r.get('type') or '').strip() in field_of}


def bare_answer(text: str) -> bool:
    """Whether a brief item is only "yes" or "no" (any case, punctuation
    aside): an outcome field's answer to the scene's question, not an
    event."""
    return re.sub(r'[\W_]+', '', text).casefold() in ('yes', 'no')


def held_entering(rows: list[dict], ids, scene_id: str, order: dict[str, int],
                  present: set[str] | frozenset = frozenset(), *,
                  chars: dict[str, str] | None = None,
                  places: dict[str, str] | None = None) -> dict[str, str]:
    """Of the promised ledger fact `ids`, each physical one an earlier
    scene set that holds entering `scene_id`: id → why it isn't asked as a
    promise (#740). It holds when it is a `state` in force entering the
    scene (`ledger.active_states`), or a fixed fact no binding fact
    supersedes. The why says whether it is asked as a fact instead: when
    its subject is `present` (through `chars` and `places`), as
    `facts_to_ask` asks it; with no subject or absent, it is said to be
    unchecked.

    Only physical facts: a `knowledge_out` fact set earlier may still be
    this scene's to deliver (the point of view learns it here, as
    `continuity` reads `knowledge_out`), so it stays a promise. One
    superseded or ended before the scene doesn't hold: the brief has the
    scene bring it back, and it stays a promise. A fact with no scene of
    the book (backstory, a cut scene) isn't an earlier scene's."""
    from storyforge.ledger import active_states
    at = order.get(scene_id)
    if at is None:
        return {}
    wanted = set(ids)
    superseded = {old.strip() for r in rows if (r.get('status') or '') == 'binding'
                  for old in (r.get('supersedes') or '').split(';') if old.strip()}
    in_force = {r['id'] for r in active_states(rows, scene_id, order, entering=True)}
    out = {}
    for r in rows:
        sid = (r.get('scene_id') or '').strip()
        if r.get('id') not in wanted or (r.get('type') or '').strip() != 'physical' \
                or sid not in order or order[sid] >= at:
            continue
        if not (r['id'] in in_force if (r.get('mutable') or '') == 'state'
                else r['id'] not in superseded):
            continue
        subject = (r.get('subject') or '').strip()
        held = f'set in {sid}, still in force entering this scene: not this scene\'s to set up'
        if subject and _lookup(subject, chars or {}, places or {}) in present:
            out[r['id']] = held + '; asked as a fact instead'
        else:
            out[r['id']] = held + ('; its subject isn\'t in the scene' if subject
                                   else '; it has no subject') + ', so it is not checked'
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
    `MAX_PROMISES`; the rest named in a note), twice each, in one call per
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
    if len(promises) > MAX_PROMISES:
        over = promises[MAX_PROMISES:]
        result.notes.append(f'{len(over)} brief promise(s) past the {MAX_PROMISES} a scene '
                            f'gets: not asked: ' + '; '.join(p.text for p in over))
        result.unverified += [_broken(p, '', 'past the cap: not asked') for p in over
                              if p.must]
        promises = promises[:MAX_PROMISES]
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
            quote, _why = _verified([a[n] for a in answers], prose)
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
    result.promise_split = split
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
                    promises: bool = True,
                    endings: list[Dispute] | None = None) -> QuestionResult:
    """Ask `scene_id`'s prose about the facts in `rows` (the ledger as the
    gate reads it, without the scene's own commitments) that hold for it
    and whose subject is present by `records` (the scene's typed state),
    its places or its prose's names, or can't be placed; about the brief's
    entering items in words; about `disputes`; whether the scene shows each
    of `endings` ending (#734, `ending_question`); and, with `promises`, whether
    it delivers each of its brief's promises (`ask_promises`, its own call
    logged beside `log_file` as `-promises`). The notes say how many were
    asked and what wasn't.

    Raises:
        QuestionError: as `ask_questions`; or scenes.csv or a registry
            can't be read.
    """
    from storyforge import ledger
    from storyforge.checker import brief_from
    from storyforge.elaborate import _read_csv, _read_csv_as_map, get_scene
    from storyforge.enrich import load_alias_map
    ref = os.path.join(project_dir, 'reference')
    try:
        order = ledger.scene_order(project_dir)
        subject_names, name_notes = ledger.subject_names(project_dir)
    except (ValueError, OSError, ledger.LedgerError) as e:
        raise QuestionError(f'{scene_id}: {e}') from e
    chars = load_alias_map(os.path.join(ref, 'characters.csv'))
    places = load_alias_map(os.path.join(ref, 'locations.csv'))
    scenes = _read_csv_as_map(os.path.join(ref, 'scenes.csv'))
    location = scenes.get(scene_id, {}).get('location') or ''
    # a shared name places only a bearer tied to the scene otherwise (#746)
    scene = get_scene(scene_id, ref) or {}
    cast = [c.strip() for col in ('characters', 'on_stage', 'pov')
            for c in (scene.get(col) or '').split(';') if c.strip()]
    seen = presence(records, chars, places, location, prose=prose, names=subject_names,
                    tied=tied_subjects(cast, rows, scene_id, order, subject_names))
    present, on_stage = seen.present, seen.on_stage
    names, registry = {}, set()
    for reg in ('characters.csv', 'locations.csv'):
        for r in _read_csv(os.path.join(ref, reg)):
            rid = (r.get('id') or '').strip()
            if rid:
                names[_norm(rid)] = (r.get('name') or rid).strip()
                registry.add(_norm(rid))
    picked = facts_to_ask(rows, scene_id, order, present, registry=registry, chars=chars,
                          places=places, on_stage=on_stage, days=scene_days(scenes))
    by_id = {r.get('id'): r for r in rows}
    result = QuestionResult(scene_id, present=sorted(present))
    result.notes += [f'{n} (who is in the scene)' for n in name_notes]
    result.notes += seen.notes
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
    # an ending claim sits with the disputes, first: it decides whether an
    # end is recorded (#756), so the cap must never cut it
    for d in endings or []:
        row = by_id.get(d.fact_id)
        if row is None:
            result.notes.append(f'ending of {d.fact_id}: no ledger fact to ask about: '
                                f'not asked, so not recorded')
            continue
        ruled.add(d.fact_id)
        questions.append(ending_question(d, row, names.get(_norm(row.get('subject') or ''),
                                                           '')))
    # the brief's entering items next: what it has holding as the scene
    # opens is the likeliest to be contradicted (#739; the cap cuts the end)
    brief = brief_from(rows, project_dir, scene_id)
    questions += [entering_question(col, item) for col, items_ in brief.entering.items()
                  for item in items_]
    # a disputed fact is asked once, as its dispute (one slip is not two)
    questions += [question_for(r, names.get(_lookup(r['subject'], chars, places),
                                            r['subject'].strip()), order)
                  for r in picked.facts if r['id'] not in ruled]
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
                            f'prose): not asked: ' + ', '.join(picked.absent))
    if picked.stale:
        cut = [q.fact_id for q in questions[MAX_QUESTIONS:] if q.fact_id in picked.stale]
        result.notes.append(f'{len(picked.stale)} state trait(s) set on an earlier day than '
                            f'this scene\'s, maybe stale (a mood, attire), asked after every '
                            f'other fact: ' + ', '.join(picked.stale)
                            + (f' ({len(cut)} past the cap, not asked: {", ".join(cut)})'
                               if cut else ''))
    # the facts' questions and the promises' are independent: asked at once
    from storyforge.runner import together
    left_out: list[str] = []
    wanted = promises_for(brief, entering=held_entering(rows, brief.promised, scene_id, order,
                                                        present, chars=chars, places=places),
                          fields=promised_fields(rows, brief.promised),
                          left_out=left_out) if promises else []
    if left_out:
        result.notes.append(f'{len(left_out)} brief promise(s) not asked: '
                            + '; '.join(left_out))
    stem, ext = os.path.splitext(log_file)
    calls = []
    if questions:
        calls.append(lambda: ask_questions(scene_id, prose, questions,
                                           model=resolve_model(model), log_file=log_file))
    if wanted:
        calls.append(lambda: ask_promises(scene_id, prose, wanted, model=resolve_model(model),
                                          log_file=f'{stem}-promises{ext}' if log_file
                                          else ''))
    answered = together(*calls)
    if questions:
        asked = answered.pop(0)
        asked.present, asked.notes = result.present, result.notes + asked.notes
        asked.unruled = result.unruled + asked.unruled
        result = asked
    if promises:
        result.unknown_brief_items = list(brief.unknown)
        result.stale_brief_items = list(brief.stale)
        if wanted:
            got = answered.pop(0)
            result.findings += got.findings
            result.unverified += got.unverified
            result.kept += got.kept
            result.kept_unverified += got.kept_unverified
            result.plan_departures += got.plan_departures
            result.promises_asked = got.promises_asked
            result.promise_split = got.promise_split
            result.misquoted += got.misquoted
            result.notes += got.notes
    result.notes.insert(0, f'{result.asked} question(s) about facts and disputes and '
                           f'{result.promises_asked} about brief promises asked, '
                           f'{len(present)} subject(s) present')
    return result


# ============================================================================
# Is a first run's finding still there? (#738)
# ============================================================================

RESOLVED_PROMPT = """You check whether a revised scene of a novel still has problems another checker found in an earlier draft of it. Each question gives one problem: the earlier draft's words, what they contradicted or what the scene's brief promised, and why it was a problem.

Answer `yes` when the scene as it now reads still has the problem: the same conflict with the same fact, in the old words or in new ones, or the brief's item still not delivered. Put in `quote` the scene's words that have it now, copied exactly: the shortest clause that shows it (empty for an item the scene leaves out). Answer `no` only when the scene clearly no longer has it: the words are gone, or changed so that they agree with the fact, or the item is now delivered; with `no`, `quote` is empty. If you can't tell, answer `yes`. Give a one-sentence reason in `why`.

## Scene: {scene_id}

{prose}

## Problems found in the earlier draft

{questions}"""


@dataclass
class Resolved:
    """`ask_resolved`'s answer, by finding (the objects passed in)."""
    #: the findings both askings said the scene no longer has
    resolved: list[Finding] = field(default_factory=list)
    #: (finding, quote) for each the scene still has, or may have: the
    #: quote is of the scene as it now reads, '' when no asking gave one
    #: found in it
    standing: list[tuple[Finding, str]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _resolved_block(n: int, f: Finding) -> str:
    if f.kind == 'broken-promise':
        said = (f' Its nearest words then: "{f.scene_quote}".' if f.scene_quote else '')
        return (f'{n}. A broken promise ({f.fact_id}): the brief promises '
                f'"{f.established_quote}".{said} Why: {f.explanation}\n'
                f'   Question: Does the scene still fail to deliver it?')
    against = ('the scene itself' if f.code == 'BLK'
               else f.source if f.established_scene else f'the ledger fact {f.fact_id}'
               if f.fact_id else 'the ledger')
    return (f'{n}. A contradiction ({f.code}): the earlier draft said "{f.scene_quote}", but '
            f'{against} has "{f.established_quote}". Why: {f.explanation}\n'
            f'   Question: Does the scene still have this problem?')


def build_resolved_prompt(scene_id: str, prose: str, findings: list[Finding],
                          asking: int = 1) -> str:
    """The problems, numbered from 1 in `findings`' order; a later asking
    lists them in reverse and says which it is (`yes_no`)."""
    order = list(enumerate(findings, start=1))
    if asking > 1:
        order.reverse()
    return _independent(RESOLVED_PROMPT.format(
        scene_id=scene_id, prose=prose.strip(),
        questions='\n\n'.join(_resolved_block(n, f) for n, f in order)), asking)


def ask_resolved(scene_id: str, prose: str, findings: list[Finding], *, model: str,
                 log_file: str = '') -> Resolved:
    """#738: whether `prose` (a scene after a fix) still has each of
    `findings` (the open checker's, on the prose before the fix), asked
    twice in one call per asking (`yes_no.ask`) on the question layer's
    model. A finding is resolved only when both askings say no; anything
    else stands (a wrong "resolved" passes prose with the error, a wrong
    "still there" costs a fix round or a look), with the first quote an
    asking that said yes gave that is in the prose (`quotes.quote_in`).
    No third asking: a split stands, as a dispute is cleared only by two
    noes.

    Raises:
        QuestionError: a refusal, an API failure, or a reply cut off or off
            the schema twice running.
    """
    result = Resolved()
    count = len(findings)
    if not count:
        return result
    answers = yes_no.ask(lambda n: build_resolved_prompt(scene_id, prose, findings, n), count,
                         model=model, log_file=log_file, tokens=max_tokens(count),
                         schema=SCHEMA, label=f'resolved {scene_id}',
                         what=f'{scene_id}: whether the first run\'s findings are still there',
                         error=QuestionError, fields=('quote', 'why'))
    gone, split = yes_no.agreed(answers, count, 'no')
    for n, f in enumerate(findings, start=1):
        if n in gone:
            result.resolved.append(f)
            continue
        quote, _ = _verified([a[n] for a in answers if a[n]['answer'] == 'yes'], prose)
        result.standing.append((f, quote))
    if split:
        result.notes.append(f'{split} split answer(s): they stand (only two noes clear one)')
    return result
