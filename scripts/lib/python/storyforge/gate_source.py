"""The gate's source check: an adaptation's prose against the source (#557).

The gate checks a scene against what the book already says, never against
the source, so in an adaptation the first telling wins even when it is the
wrong one (B-031: a scene that told the poem's history the poem's way was
blocked by an earlier scene that hadn't), and facts misread from the prose
are committed (B-027: four facts on `grendel-takes-thirty-sleepers` the poem
contradicts). In a `faithful` adaptation (`source:` block, `mode: faithful`)
`review` makes one call (evaluation tier) for a scene mapped in
`reference/source-map.csv`, after the check, given the source scenes it
adapts (their summary, brief and prose) and, for each verified contradiction
with an earlier scene, the source scenes behind that scene (when they fit
`MAX_SOURCE_CHARS`; when they don't, or that scene isn't mapped, it is still
ruled on from this scene's source, #742). It rules:

- each proposed commitment: does the source contradict it? One it does is
  still committed (#742: the ledger records what the book says, and the
  check rules by the source's text, whose own slips differ from the
  the departure is reported (`GateResult.source_departs`) and
  the scene listed for the author (below). A verdict whose reasoning ends
  by concluding the source agrees (`says_agrees`), or that rests on a known
  slip of the source's text with the fact on the original's side
  (`_follows_original`; `source.read_errata`, sent with the call so the
  call rules by the original), is not a departure (a note). While the
  scene is listed, every fact of it is sent again, so a departure is
  re-ruled before the listing can come off;
- each verified contradiction with an earlier scene: which side the source
  backs, with a source quote code finds in the source prose sent
  (`_quoted`: one unbroken run of `MIN_SOURCE_QUOTE_WORDS` words, never the
  summary or brief; one not found is a note and the finding stands). When it backs this scene, the finding doesn't block it
  (`GateResult.source_backed`): on commit the earlier scene's commitments
  stating it become `superseded` and this scene's are committed, so later
  scenes follow the source (`gate._source_supersede`; one whose earlier fact
  can't be found is held back instead), and the earlier scene is listed in
  working/gate-source-fix.csv for the author (`gate.mark_source_fix`: apart
  from gate-pending.csv, so it never stops drafting and a re-check never
  clears it; only a commit of that scene with other prose does, which also
  retires its superseded rows, and until then a re-gate never binds a
  superseded fact again, `gate._keep_superseded`). A scene with a fact
  the source contradicts is listed the same way;
- each other blocking finding, the scene's own (blocking, possession) and
  those against the ledger, a bible or the calendar (#742): does the source
  narrate this same sequence? `source-has-it` (with a quote code finds in
  the prose of the source this scene adapts), `prose-departs` or `silent`. `source-has-it` doesn't clear it
  (Ben, 2026-11-26: a physical slip inside a scene is smoothed even when
  the original has it): the finding still blocks and goes to the fix, and
  the source's passage is listed for the author in
  working/gate-source-notes.csv (`GateResult.source_has_it`,
  `gate.note_source_has_it`), never a silent pass.

With contradictions or findings to rule on, the call is also handed the
source's own facts (its fact ledger, `source.entering_state` through this
scene's source scenes, at most `MAX_SOURCE_FACTS`) on the deaths, wounds
and healings, and armour and weapons of the people they name (#747): a
healing told in the source is in front of the ruling on "he is back at the
front". Retrieval only: a quote still has to come from the source prose.

Cost: only facts new to the scene are sent, an unchanged re-check makes no
call, a fix round with the same facts reuses the ruling (`_MEMO`), source
prose is cut at `MAX_SCENE_PROSE_CHARS` a scene and `MAX_SOURCE_CHARS` a
call, and `write`'s forecast adds `COST_PER_SCENE`.

A departure the version rules (`source.rules`) or the map row's treatment
or note authorize is not a contradiction, nor is staging (order inside the
scene, a speech dramatised or partly reported) that changes no outcome,
cause or what a character knows when: the drafting prompt allows it (#658). A project without a source, in
`free` mode, or a scene not mapped (or invented) makes no call, and the
check says why in a note. A call that fails is a note too, never a stop:
the consistency check stands on its own.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field

#: The pending-row command for an earlier scene the source contradicts where
#: a later scene follows it (`gate._apply_source`): the author's to fix
SOURCE_FIX = 'source-fix'

#: The most source text (characters) one call is sent: past it, the earlier
#: scenes' sources are left out and contradictions with them not ruled on
MAX_SOURCE_CHARS = 40000
#: The most of one source scene's prose sent (#557's review: a long book of
#: the Iliad mapped to one scene would fill the call); the rest is cut, and
#: the cut said in the prompt
MAX_SCENE_PROSE_CHARS = 12000
#: The fewest words a source quote may have to count as found: "the
#: spear" is in every book of the Iliad
MIN_SOURCE_QUOTE_WORDS = 4
#: The most source facts (`source.entering_state`) a ruling is handed on
#: the people in its findings (#747): the latest are kept
MAX_SOURCE_FACTS = 20
#: What `write`'s forecast adds to each gated scene of a faithful
#: adaptation: one Sonnet call with up to `MAX_SOURCE_CHARS` of source (an
#: estimate, not measured)
COST_PER_SCENE = 0.10

SCHEMA = {
    'type': 'object',
    'properties': {
        'facts': {'type': 'array', 'items': {
            'type': 'object',
            'properties': {'n': {'type': 'integer'},
                           'verdict': {'type': 'string',
                                       'enum': ['agrees', 'contradicts', 'not-in-source']},
                           'why': {'type': 'string'}},
            'required': ['n', 'verdict', 'why'], 'additionalProperties': False}},
        'contradictions': {'type': 'array', 'items': {
            'type': 'object',
            'properties': {'n': {'type': 'integer'},
                           'backs': {'type': 'string', 'enum': ['this', 'earlier', 'neither']},
                           'source_quote': {'type': 'string'},
                           'why': {'type': 'string'}},
            'required': ['n', 'backs', 'source_quote', 'why'],
            'additionalProperties': False}},
        'findings': {'type': 'array', 'items': {
            'type': 'object',
            'properties': {'n': {'type': 'integer'},
                           'verdict': {'type': 'string',
                                       'enum': ['source-has-it', 'prose-departs', 'silent']},
                           'source_quote': {'type': 'string'},
                           'why': {'type': 'string'}},
            'required': ['n', 'verdict', 'source_quote', 'why'],
            'additionalProperties': False}},
    },
    'required': ['facts', 'contradictions', 'findings'],
    'additionalProperties': False,
}


class SourceReviewError(RuntimeError):
    """The call failed, was cut off, or its reply isn't the schema."""


#: The last sentence of a "contradicts" whose reasoning concludes the
#: source agrees (#742: 5 of 18 on *Wrath Like Smoke*: "...so the source is
#: not contradicted", "(Wait: this matches the source.)"). Only a whole
#: closing sentence of agreement counts (`says_agrees`): partial agreement
#: ("only the count matches the source") or a denial inside a departure
#: ("not only contradicts") is still a departure (#742's review, SF-2)
_AGREES_END = re.compile(
    r"(?:(?:so|thus|therefore|hence|and|wait)\s*,?\s+)?"
    r"(?:this|it|that|the\s+(?:source|prose|fact|scene|statement))\s+"
    r"(?:is\s+(?:not|never)\s+contradicted|is\s+uncontradicted"
    r"|(?:matches|agrees\s+with|is\s+consistent\s+with)\s+the\s+source(?:\s+text)?)",
    re.IGNORECASE)


def says_agrees(why: str) -> bool:
    """Whether a "contradicts" verdict's reasoning ends by concluding the
    source agrees: its last sentence is wholly `_AGREES_END`."""
    text = re.sub(r'[\s.!?)\]"\']+$', '', why or '')
    last = re.split(r'[.,;:!?(]\s*', text)[-1].strip()
    return bool(last and _AGREES_END.fullmatch(last))


@dataclass
class SourceReview:
    #: (index into the proposed rows, why) for each fact the source
    #: contradicts: kept, and reported (#742: never dropped)
    departs: list[tuple[int, str]] = field(default_factory=list)
    #: the indexes of the facts the reply ruled on (any verdict)
    ruled: set[int] = field(default_factory=set)
    #: (index into the contradictions sent, why) for each the source backs
    #: this scene on, with a source quote found in the source sent
    backs_scene: list[tuple[int, str]] = field(default_factory=list)
    #: (index into the blocking findings sent, source quote, why) for each
    #: the source narrates the same way, the quote found (#742)
    has_it: list[tuple[int, str, str]] = field(default_factory=list)
    #: what wasn't checked, and why
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Setup:
    """What `setup` found: the source scenes behind each scene, or why the
    check doesn't run."""
    refs: dict[str, list[tuple[str, str]]]
    rules: str
    map_rows: dict[str, dict[str, str]]
    skip: str = ''
    #: (source slug, source scene id) → its known slips (`source.read_errata`)
    errata: dict = field(default_factory=dict)
    #: what the check can't use and says on every run (an errata row naming
    #: a source scene the source hasn't got, #742's review SF-4)
    warnings: tuple = ()

    def active(self) -> bool:
        return not self.skip and bool(self.refs)


def setup(project_dir: str) -> Setup | None:
    """None for a project with no `source:` block (nothing to say); a
    `Setup` with `skip` when the check can't run (free mode, no map, a bad
    config)."""
    from storyforge import source
    try:
        cfg = source.read_config(project_dir)
    except source.SourceError as e:
        return Setup({}, '', {}, skip=f'the source config can\'t be read ({e})')
    if cfg is None:
        return None
    if cfg.mode != 'faithful':
        return Setup({}, '', {}, skip=f'source.mode is {cfg.mode}: fidelity isn\'t checked')
    try:
        rows = source.read_source_map(project_dir)
        rules = source.read_rules(project_dir, cfg)
        cat = source.catalogue(project_dir, cfg)
        errata = source.read_errata(project_dir, cfg)
    except (source.SourceError, OSError, ValueError) as e:
        return Setup({}, '', {}, skip=f'the source can\'t be read ({e})')
    if not rows:
        return Setup({}, rules, {}, skip='reference/source-map.csv is missing or empty')
    by_scene = source.map_rows_by_scene(rows)
    refs: dict[str, list[tuple[str, str]]] = {}
    for sid, row in by_scene.items():
        if row.get('treatment') == 'invent':
            continue
        found = [source.resolve_source_id(r, cat)
                 for r in source.split_ids(row.get('source_scenes', ''))]
        if found and all(found):
            refs[sid] = found
    warnings = tuple(
        f'{cfg.errata_path(cfg.project(slug))}: the known slip at '
        f'{e.ref or "(no ref)"} names source scene {sid!r}, which source {slug} hasn\'t '
        f'got: it is never sent; fix its source_scene'
        for (slug, sid), slips in errata.items() if sid not in cat.get(slug, {})
        for e in slips)
    return Setup(refs, rules, by_scene, errata=errata, warnings=warnings)


def _source_text(project_dir: str, refs: list[tuple[str, str]]) -> str:
    """The source scenes `refs` (their brief, and prose cut at
    `MAX_SCENE_PROSE_CHARS`) for the prompt."""
    from storyforge.prompts_source import source_scene_block
    blocks = []
    for slug, sid in refs:
        text = source_scene_block(project_dir, slug, sid, prose=True)
        start = text.find('<source-prose')
        if start >= 0 and len(text) - start > MAX_SCENE_PROSE_CHARS:
            text = (text[:start + MAX_SCENE_PROSE_CHARS]
                    + f'\n[... the rest of {slug}:{sid} is not shown]\n</source-prose>')
        blocks.append(text)
    return '\n\n'.join(blocks)


def has_source_prose(project_dir: str, refs: list[tuple[str, str]]) -> bool:
    from storyforge import source
    return any(source.source_prose(project_dir, slug, sid) for slug, sid in refs)


#: (scene, facts sent, contradictions sent, findings sent) → the ruling, for
#: this process: a fix round re-gating the same facts doesn't pay again
#: (#557's review)
_MEMO: dict[tuple, 'SourceReview'] = {}


def errata_lines(ctx: Setup, refs: list[tuple[str, str]]) -> list[str]:
    """The known slips (`Setup.errata`) of the source scenes `refs`, a line
    each, for the prompt."""
    out = []
    for slug, sid in refs:
        for e in ctx.errata.get((slug, sid), []):
            ref = f'{e.ref}, ' if e.ref else ''
            out.append(f'- {ref}{sid}: {e.has_label} has "{e.has}"; {e.original_label} has '
                       f'"{e.original}"' + (f' (checked: {e.checked})' if e.checked else ''))
    return out


def build_prompt(scene_id: str, prose: str, facts: list[dict[str, str]],
                 contradictions: list[tuple[str, str, str, str]], this_source: str,
                 earlier_sources: dict[str, str], rules: str, treatment: str,
                 note: str, findings: list[tuple[str, str, str]] = (),
                 errata: list[str] = (), source_facts: list[str] = ()) -> str:
    """`contradictions`: (this scene's words, the earlier scene, its words,
    the check's explanation). `earlier_sources`: earlier scene id → the
    source text behind it; a contradiction whose earlier scene has none is
    ruled on from this scene's source (#742). `findings`: (the scene's
    words, the words they are set against, the explanation) for each other
    blocking finding (#742). `errata`: `errata_lines`. `source_facts`:
    `prompts_source.entering_lines` of the source's facts on the people in
    the contradictions and findings (#747); none, no section."""
    fact_lines = '\n'.join(f'{n}. {f.get("statement", "")} (the scene\'s words: '
                           f'"{f.get("quote", "")}")'
                           for n, f in enumerate(facts, start=1)) or '(none)'
    con_lines = '\n'.join(
        f'{n}. This scene says "{q}"; earlier scene {sid} says "{eq}". The check: {why}'
        + ('' if sid in earlier_sources else
           f' (The source behind {sid} is not shown: rule from the source this scene adapts.)')
        for n, (q, sid, eq, why) in enumerate(contradictions, start=1)) or '(none)'
    finding_lines = '\n'.join(
        f'{n}. "{q}"' + (f' against "{other}"' if other and other != q else '')
        + f'. The check: {why}'
        for n, (q, other, why) in enumerate(findings, start=1)) or '(none)'
    earlier = '\n\n'.join(f'### The source behind {sid}\n\n{text}'
                          for sid, text in earlier_sources.items()) or '(none)'
    slips = ('\n\n## Known slips of the source text\n\nThe source text departs from its '
             'original here. Rule by the original: a fact or finding that follows the '
             'original is not a departure.\n\n' + '\n'.join(errata)) if errata else ''
    known = ('\n\n## The source\'s facts on these people\n\nFrom the source\'s fact ledger, '
             'oldest first: what the source tells, up to and through the passage this scene '
             'adapts, of the deaths, wounds and healings, and armour and weapons of the '
             'people in the contradictions and findings (a source scene each; [until …] '
             'names the source scene that state ends in). Use them to find what the source '
             'has happened to a person by this scene (a wound healed, a death, armour '
             'changing hands). They were read from the source by a model and can miss or '
             'misread: rule by the source prose, and copy every `source_quote` from the '
             'source prose shown above.\n\n' + '\n'.join(source_facts)) if source_facts else ''
    return f"""Scene {scene_id} of a faithful adaptation is checked against its source. Rule on three lists.

1. Facts: each was read from the scene's prose. Does the source contradict it? `contradicts` only when the source says otherwise (a different person, count, place, order, cause or outcome), not when the source is silent or the fact adds detail (`not-in-source`). A departure the version rules or the map's treatment or note allow is not a contradiction, nor is staging: order inside the scene, or a speech dramatised or partly reported, that changes no outcome, no cause and nothing a character knows when. When your reasoning finds the source agrees, the verdict is `agrees`.
2. Contradictions: each is between this scene and an earlier scene of the adaptation. Which side does the source back? `this` when the source tells it this scene's way, `earlier` when the earlier scene's, `neither` when the source backs neither or is silent.
3. Findings: each is a problem the check found in this scene (its own staging, what a character holds, or a fact of the book). Does the source narrate this same sequence? `source-has-it` only when the source itself tells what the finding flags, the same way (the source's own oddity); `prose-departs` when the source tells it otherwise; `silent` when the source doesn't tell it, or the prose adds to it what the source doesn't have (staging, a direction, a detail the source never gives). When the source has part of it and the prose adds the part the finding flags, that is not `source-has-it`.

For `this` and `source-has-it`, give `source_quote`: one unbroken run of the source's own prose (not its summary or brief), copied exactly, at least {MIN_SOURCE_QUOTE_WORDS} words, with no `...`. For `this` it may come from any source prose shown; for `source-has-it`, from the prose of the source this scene adapts. Otherwise give an empty `source_quote`. Give each `why` in one sentence, quoting the source.

## Version rules

{rules or '(none)'}

## The map

Treatment: {treatment or '(none)'}. Note: {note or '(none)'}.{slips}

## The source this scene adapts

{this_source}

## Earlier scenes' sources

{earlier}{known}

## Scene {scene_id}

{prose}

## Facts

{fact_lines}

## Contradictions

{con_lines}

## Findings

{finding_lines}"""


_PROSE = re.compile(r'<source-prose[^>]*>\n?(.*?)</source-prose>', re.S)


def source_prose_of(text: str) -> str:
    """The source's own prose in `text` (a `_source_text`): its
    `<source-prose>` parts, never the summary or brief (#742's review,
    CR-2)."""
    return '\n\n'.join(_PROSE.findall(text))


def _quoted(quote: str, prose: str) -> bool:
    """Whether `quote` is the source's own words: one unbroken run of at
    least `MIN_SOURCE_QUOTE_WORDS` words of `prose` (no `...` joining
    pieces, #742's review CR-3)."""
    from storyforge.quotes import quote_in, word_count
    if '...' in quote or '\u2026' in quote:
        return False
    return word_count(quote) >= MIN_SOURCE_QUOTE_WORDS and quote_in(prose, quote)


def _follows_original(fact: dict[str, str], why: str, errata: list) -> str:
    """The ref of a known slip (`source.Erratum`) a "contradicts" on `fact`
    rests on, with the fact on the original's side: the fact's own words
    (statement or quote) have the original's and not the slip's, and `why`
    cites the slip. '' when none: a fact that follows the slip, against the
    original, is a departure (#742's review, CR-1, SF-3)."""
    from storyforge.quotes import quote_in
    own = f'{fact.get("statement", "")}\n{fact.get("quote", "")}'
    for e in errata:
        if (quote_in(own, e.original) and not quote_in(own, e.has)
                and quote_in(why, e.has)):
            return e.ref or e.source_scene
    return ''


def _one_line(text: str) -> str:
    return ' '.join((text or '').split())


def _source_facts(project_dir: str, scene_id: str, refs: list[tuple[str, str]],
                  contradictions: list, findings: list, notes: list[str]) -> list[str]:
    """The source's facts (`source.entering_state`, through this scene's own
    source scenes) on the people the contradictions and findings name, or,
    naming none the source knows, the scene's cast: retrieval for the
    ruling (#747). [] with nothing to rule on. What can't be read is a
    note, and the ruling goes on without them."""
    from storyforge import source
    from storyforge.prompts_source import entering_lines
    if not contradictions and not findings:
        return []
    text = '\n'.join(part for f in [*contradictions, *findings]
                     for part in (f.scene_quote, f.established_quote, f.explanation))
    try:
        people = (source.named_in(project_dir, [s for s, _ in refs], text)
                  or source.scene_cast(project_dir, scene_id, refs))
        state = source.entering_state(project_dir, refs, people, through=True,
                                      limit=MAX_SOURCE_FACTS)
    except (source.SourceError, OSError, UnicodeDecodeError) as e:
        notes.append(f'the source\'s facts on the people in the findings could not be read '
                     f'({e}): ruled without them')
        return []
    notes.extend(state.notes)
    return entering_lines(state.facts, quotes=True)


def review(project_dir: str, scene_id: str, prose: str, facts: list[dict[str, str]],
           contradictions: list, *, model: str, log_file: str,
           ctx: Setup, findings: list = ()) -> SourceReview:
    """Rule on `facts` (the proposed rows), `contradictions` (verified
    `checker.Finding`s with an earlier scene, by index) and `findings` (the
    scene's other blocking `checker.Finding`s, by index, #742) for
    `scene_id`. `ctx` must have no `skip` and map the scene (`setup`).

    Raises:
        SourceReviewError: the call failed or its reply can't be used.
    """
    from storyforge.api import extract_text, invoke_to_file, is_truncated
    from storyforge.source import SourceError
    out = SourceReview()
    key = (scene_id, tuple((f.get('statement', ''), f.get('quote', '')) for f in facts),
           tuple((c.scene_quote, c.established_scene, c.established_quote)
                 for c in contradictions),
           tuple((f.scene_quote, f.established_quote, f.explanation) for f in findings))
    if key in _MEMO:
        return _MEMO[key]
    refs = list(ctx.refs[scene_id])
    try:
        if not has_source_prose(project_dir, ctx.refs[scene_id]):
            raise SourceReviewError(f'{scene_id}: its source scenes have no prose')
        this = _source_text(project_dir, ctx.refs[scene_id])
        budget = MAX_SOURCE_CHARS - len(this)
        earlier: dict[str, str] = {}
        unshown: set[str] = set()
        for f in contradictions:
            sid = f.established_scene
            if sid in earlier or sid in unshown:
                continue
            if sid not in ctx.refs:
                out.notes.append(f'{sid} is not mapped to the source: its contradiction with '
                                 f'{scene_id} is ruled on from {scene_id}\'s source alone')
                unshown.add(sid)
                continue
            text = _source_text(project_dir, ctx.refs[sid])
            if len(text) > budget:
                out.notes.append(f'the source behind {sid} would pass {MAX_SOURCE_CHARS} '
                                 f'characters: its contradiction is ruled on from '
                                 f'{scene_id}\'s source alone')
                unshown.add(sid)
                continue
            budget -= len(text)
            earlier[sid] = text
            refs += [r for r in ctx.refs[sid] if r not in refs]
    except (SourceError, OSError, UnicodeDecodeError, KeyError, ValueError) as e:
        raise SourceReviewError(f'{scene_id}: the source can\'t be read: {e}') from e
    if not facts and not contradictions and not findings:
        return out
    # #742's review (CR-2, CR-7): a quote is checked against the source's
    # own prose; a same-scene finding's against this scene's source alone
    this_prose = source_prose_of(this)
    shown = '\n\n'.join([this_prose, *(source_prose_of(t) for t in earlier.values())])
    # the facts are this scene's: only its own source scenes' slips clear one
    slips = [e for slug, sid in ctx.refs[scene_id] for e in ctx.errata.get((slug, sid), [])]
    source_facts = _source_facts(project_dir, scene_id, ctx.refs[scene_id],
                                 contradictions, findings, out.notes)
    row = ctx.map_rows.get(scene_id, {})
    prompt = build_prompt(scene_id, prose, facts,
                          [(c.scene_quote, c.established_scene, c.established_quote,
                            c.explanation) for c in contradictions],
                          this, earlier, ctx.rules, row.get('treatment', ''),
                          row.get('note', ''),
                          [(f.scene_quote, f.established_quote, f.explanation)
                           for f in findings],
                          errata_lines(ctx, refs), source_facts)
    try:
        response = invoke_to_file(prompt, model, log_file, 4000, output_schema=SCHEMA,
                                  label=f'source check {scene_id}')
        if is_truncated(response):
            raise ValueError('the reply hit its token limit')
        reply = json.loads(extract_text(response))
        for item in reply['facts']:
            n = int(item['n'])
            if not 1 <= n <= len(facts):
                continue
            out.ruled.add(n - 1)
            if item['verdict'] != 'contradicts':
                continue
            why = str(item.get('why', ''))
            statement = _one_line(facts[n - 1].get('statement', ''))[:100]
            slip = _follows_original(facts[n - 1], why, slips)
            if says_agrees(why):
                out.notes.append(f'"contradicts" set aside, its own reasoning concludes the '
                                 f'source agrees: {statement} ({_one_line(why)[:160]})')
            elif slip:
                out.notes.append(f'"contradicts" set aside, it rests on a known slip of the '
                                 f'source text ({slip}) and the fact follows the original: '
                                 f'{statement}')
            else:
                out.departs.append((n - 1, why))
        for item in reply['contradictions']:
            n = int(item['n'])
            if item['backs'] != 'this' or not 1 <= n <= len(contradictions):
                continue
            quote, why = str(item.get('source_quote', '')), str(item.get('why', ''))
            if _quoted(quote, shown):
                out.backs_scene.append((n - 1, f'{why} (the source: "{_one_line(quote)}")'))
            else:
                out.notes.append(f'the source was said to back {scene_id} against '
                                 f'{contradictions[n - 1].established_scene}, but its quote '
                                 f'is not words of the source sent ("{_one_line(quote)[:120]}"): '
                                 f'the contradiction stands')
        for item in reply.get('findings') or []:
            n = int(item['n'])
            if item['verdict'] != 'source-has-it' or not 1 <= n <= len(findings):
                continue
            quote, why = str(item.get('source_quote', '')), str(item.get('why', ''))
            if _quoted(quote, this_prose):
                out.has_it.append((n - 1, _one_line(quote), why))
            else:
                out.notes.append(f'the source was said to have "'
                                 f'{_one_line(findings[n - 1].scene_quote)[:80]}", but its '
                                 f'quote is not words of the source this scene adapts '
                                 f'("{_one_line(quote)[:120]}"): not listed')
    except (RuntimeError, ValueError, KeyError, TypeError) as e:
        raise SourceReviewError(f'{scene_id}: the source check failed: {e}') from e
    _MEMO[key] = out
    return out


def log_file(log_dir: str, scene_id: str) -> str:
    return os.path.join(log_dir, f'gate-source-{scene_id}.json')
