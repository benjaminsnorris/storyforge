"""Text fidelity: the upper tiers checked against the book's own prose.

The floor checks test the tiers' form, the boundary checks compare each tier
with the next, and story-power scores the pitch as a pitch; none of them
reads the book. On an extracted book every tier is derived from the same
scene data, so the boundary checks agree even where both tiers are wrong
(storyforge-evals F-161: 98 of 105 "both are right" on three books whose
synopses had wrong causes, squeezed processes and readings from other
works). This check reads the prose.

Two passes, both on the synthesis tier:

1. **Claims** (one call): the logline, synopsis, act-shape, theme and spine
   events are split into checkable claims, each with the 1-4 scenes where the
   text should show it. Each architecture anchor's summary is a claim about
   its own scene, without a call.
2. **Verify** (one call per batch): claims are batched by the scenes they
   cite, and each batch is judged against those scenes' prose only:
   `supported`, `contradicted`, `not_shown` (the passages don't show it,
   whatever is true elsewhere) or `overreach` (an interpretation the passages
   don't bear out). Each verdict quotes the passage and, unless supported,
   suggests a correction.

Output: `working/scores/text-fidelity/<timestamp>/claims.csv` and
`report.md`. Report-only: nothing in the project is changed.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

from .common import log

VERDICTS = ('supported', 'contradicted', 'not_shown', 'overreach')
UNCHECKED = 'unchecked'   # a batch that failed, or a claim whose scenes have no prose
KINDS = ('event', 'cause', 'order', 'outcome', 'interpretation')
SECTIONS = ('logline', 'synopsis', 'act-shape', 'theme')
MAX_SCENES_PER_CLAIM = 4
BATCH_WORDS = 12000          # prose per verify call
BATCH_CLAIMS = 40            # claims per verify call (a verdict is ~100 output tokens)
CLAIMS_OUTPUT_TOKENS = 32000   # story-architecture.md's motif table alone can hold 50 claims
VERIFY_OUTPUT_TOKENS = 8000
CLAIM_COLUMNS = ['n', 'section', 'kind', 'claim', 'scenes', 'verdict', 'evidence',
                 'correction']


class FidelityError(Exception):
    """A pass that can't finish: an API error, a refusal, a cut-off reply, or
    an answer still unusable after one retry."""


class _Problems(ValueError):
    def __init__(self, problems: list[str]):
        super().__init__('; '.join(problems))
        self.problems = problems


@dataclass
class Claim:
    section: str                 # logline / synopsis / act-shape / theme / spine:<id> / architecture:<id>
    kind: str
    claim: str
    scenes: list[str]
    verdict: str = ''
    evidence: str = ''
    correction: str = ''


@dataclass
class Result:
    claims: list[Claim] = field(default_factory=list)
    output_dir: str = ''
    cost: float = 0.0
    notes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------

def _rows(project_dir: str, name: str) -> list[dict[str, str]]:
    from .elaborate import _read_csv
    return _read_csv(os.path.join(project_dir, 'reference', name))


def _scenes(project_dir: str) -> list[dict[str, str]]:
    from .extract_acts import INACTIVE, in_order
    return [r for r in in_order(_rows(project_dir, 'scenes.csv'))
            if r.get('status', '').strip().lower() not in INACTIVE]


def _prose(project_dir: str, sid: str) -> str:
    path = os.path.join(project_dir, 'scenes', f'{sid}.md')
    if not os.path.isfile(path):
        return ''
    with open(path, encoding='utf-8') as f:
        return f.read().strip()


@dataclass
class Tiers:
    summary: dict[str, str]                  # section -> text
    spine: list[dict[str, str]]
    anchors: dict[str, list[str]]           # spine id -> anchor scene ids
    architecture: list[dict[str, str]]
    story_architecture: list[tuple[str, str]] = field(default_factory=list)   # (section, text)

    def empty(self) -> bool:
        return not (any(self.summary.values()) or self.spine or self.architecture
                    or self.story_architecture)

    def summary_docs(self) -> list[tuple[str, str]]:
        """The story summary's sections and the spine events, as (section, text)."""
        docs = [(s, self.summary[s]) for s in SECTIONS if self.summary.get(s)]
        for e in self.spine:
            anchors = ', '.join(self.anchors.get(e['id'], [])) or 'none'
            docs.append((f'spine:{e["id"]}', f'{e.get("summary", "").strip()} '
                                             f'(its anchor scenes: {anchors})'))
        return docs


#: story-architecture.md sections that are counted from the CSVs, not read
#: from the book, so there is nothing in the prose to check them against
_COUNTED_SECTIONS = frozenset({'length', 'novel identity summary'})


def story_architecture_sections(path: str) -> list[tuple[str, str]]:
    """`story-architecture.md` as (section, text): one section per `##` or
    `###` heading, named `story-architecture:<heading>` (`<## heading> /
    <### heading>` under a `##`), with what the CSVs count left out (the
    length sections, each act's share line, a table of numbers) and a
    two-column table's rows as `cell: cell` lines."""
    import re
    if not os.path.isfile(path):
        return []
    with open(path, encoding='utf-8') as f:
        text = re.sub(r'<!--.*?-->', '', f.read(), flags=re.S)
    sections: list[tuple[str, list[str]]] = []
    top = ''
    for line in text.splitlines():
        m = re.match(r'^(#{2,3})\s+(.*?)\s*$', line)
        if m:
            if len(m.group(1)) == 2:
                top = m.group(2)
                name = top
            else:
                name = f'{top} / {m.group(2)}' if top else m.group(2)
            sections.append((name, []))
            continue
        if not sections or line.startswith('# ') or line.strip() == '---':
            continue
        if re.match(r'^\*\*[^*]*% of the novel', line.strip()):
            continue
        if line.lstrip().startswith('|'):
            cells = [c.strip() for c in line.strip().strip('|').split('|')]
            if all(re.fullmatch(r':?-+:?', c) for c in cells if c):
                continue
            if any(re.fullmatch(r'[\d,.%~]+', c) for c in cells):
                continue                       # a counted table (POV scenes, words)
            if len(cells) == 2 and cells[0].lower() not in ('motif',):
                line = f'- {cells[0]}: {cells[1]}'
            elif len(cells) == 2:
                continue                       # the header row
        sections[-1][1].append(line)
    out = []
    for name, lines in sections:
        last = name.split(' / ')[-1].lower()
        body = '\n'.join(lines).strip()
        if last in _COUNTED_SECTIONS or name.lower() in _COUNTED_SECTIONS or not body:
            continue
        out.append((f'story-architecture:{name}', body))
    return out


def read_tiers(project_dir: str) -> Tiers:
    """The upper tiers as written. A story summary still the init template
    counts as empty (`common.is_unfilled_template`)."""
    from .common import parse_story_summary, is_unfilled_template, STORY_SUMMARY_PATH
    summary = {s: '' for s in SECTIONS}
    path = os.path.join(project_dir, STORY_SUMMARY_PATH)
    if os.path.isfile(path) and not is_unfilled_template(path):
        parsed = parse_story_summary(project_dir) or {}
        summary = {'logline': parsed.get('logline', ''), 'synopsis': parsed.get('synopsis', ''),
                   'act-shape': parsed.get('act_shape', ''), 'theme': parsed.get('theme', '')}
    arch = _rows(project_dir, 'architecture.csv')
    anchors: dict[str, list[str]] = {}
    for r in arch:
        if r.get('spine_event', '').strip():
            anchors.setdefault(r['spine_event'].strip(), []).append(r['id'])
    sa_path = os.path.join(project_dir, 'reference', 'story-architecture.md')
    sa = ([] if os.path.isfile(sa_path) and is_unfilled_template(sa_path)
          else story_architecture_sections(sa_path))
    return Tiers({k: v.strip() for k, v in summary.items()}, _rows(project_dir, 'spine.csv'),
                 anchors, arch, sa)


# ---------------------------------------------------------------------------
# Pass 1: claims
# ---------------------------------------------------------------------------

def _schema_claims() -> dict:
    from .extract import _object, _STR, _STR_LIST
    return _object({'claims': {'type': 'array', 'items': _object({
        'section': _STR, 'kind': {'type': 'string', 'enum': list(KINDS)},
        'claim': _STR, 'scenes': _STR_LIST})}})


def _schema_verdicts() -> dict:
    from .extract import _object, _STR
    return _object({'verdicts': {'type': 'array', 'items': _object({
        'n': {'type': 'integer'}, 'verdict': {'type': 'string', 'enum': list(VERDICTS)},
        'evidence': _STR, 'correction': _STR})}})


CLAIMS_SCHEMA = _schema_claims()
VERDICTS_SCHEMA = _schema_verdicts()


def _retry_block(problems: list[str] | None) -> str:
    if not problems:
        return ''
    return ('\n## Your previous answer could not be used\n\n'
            + '\n'.join(f'- {p}' for p in problems) + '\n\nAnswer again with these fixed.\n')


def build_claims_prompt(docs: list[tuple[str, str]], scenes: list[dict[str, str]],
                        problems: list[str] | None = None) -> str:
    """`docs` is (section, text) pairs: `Tiers.summary_docs()` or
    `Tiers.story_architecture`, one claims call each."""
    docs = [f'### {name}\n\n{text}' for name, text in docs]
    scene_lines = '\n'.join(f'{r.get("seq", "")}. {r["id"]} | {r.get("title", "").strip()} | '
                            f'{r.get("summary", "").strip()}' for r in scenes)
    return f"""These documents summarize a book. Each will be checked against the book's prose. Split them
into claims that can be checked.

## The documents

{chr(10).join(docs)}

## The book's scenes, in reading order (seq. id | title | summary)

{scene_lines}
{_retry_block(problems)}
## Answer

`claims`: every claim the documents make, in the order they make it. A claim is
one statement the text can bear out or not: who did what, why, in what order,
with what outcome, or what the book means. Split a sentence that says several
things; don't split one thing into several claims. Leave out nothing a reader
could get wrong, including small words that carry weight ("finally", "all",
"the last", "because", "after").

- `section`: the document it comes from, exactly as headed above.
- `kind`: `event` (what happens), `cause` (why), `order` (before or after),
  `outcome` (how it ends), or `interpretation` (what it means: theme, motive,
  judgment).
- `claim`: the claim in the document's own words, as far as possible.
- `scenes`: the ids (not the seq numbers) of the 1-{MAX_SCENES_PER_CLAIM} scenes
  where the text shows it, from the list above. For a claim about a process ("loses all his gold"),
  give the scenes where it starts and where it ends. For an interpretation,
  give the scenes that bear on it most directly."""


def parse_claims(reply: str, docs: list[tuple[str, str]], scenes: list[dict[str, str]],
                 every_section: bool = True, salvage: list[str] | None = None) -> list[Claim]:
    """The claims in a reply about `docs`. With `every_section`, a document
    with no claim is sent back (story-architecture.md's sections, some of
    which describe the prose rather than the story, may have none)."""
    from .extract import _json_answer
    data = _json_answer(reply, CLAIMS_SCHEMA)
    ids = {r['id'] for r in scenes}
    # A reply may cite a scene by its seq, the number before the id in the
    # list (Eighty Days: 213 such citations in one reply); read it as the id
    by_seq = {r.get('seq', '').strip(): r['id'] for r in scenes if r.get('seq', '').strip()}
    sections = {name for name, _ in docs}
    claims, problems = [], []
    for i, c in enumerate(data['claims'], 1):
        if not isinstance(c, dict) or not isinstance(c.get('scenes'), list):
            problems.append(f'claim {i} is not an object with a list of scenes')
            continue
        sec = str(c.get('section', '')).strip()
        cited = [str(s).strip() for s in c.get('scenes', []) if str(s).strip()]
        cited = [s if s in ids else by_seq.get(s, s) for s in cited]
        if c.get('kind') not in KINDS:
            problems.append(f'claim {i}: kind {c.get("kind")!r} is not one of {", ".join(KINDS)}')
        unknown = [s for s in cited if s not in ids]
        if sec not in sections:
            problems.append(f'claim {i}: section {sec!r} is not one of the documents')
        if not cited:
            problems.append(f'claim {i} cites no scene')
        elif unknown:
            problems.append(f'claim {i} cites scene(s) not in the list: '
                            + ', '.join(repr(s) for s in unknown))
        elif len(cited) > MAX_SCENES_PER_CLAIM:
            problems.append(f'claim {i} cites {len(cited)} scenes; at most '
                            f'{MAX_SCENES_PER_CLAIM}')
        if not str(c.get('claim', '')).strip():
            problems.append(f'claim {i} is empty')
        claims.append(Claim(sec, str(c.get('kind', 'event')), str(c.get('claim', '')).strip(),
                            cited))
    missing = sections - {c.section for c in claims}
    if missing and every_section:
        problems.append('no claims from: ' + ', '.join(sorted(missing)))
    if problems and salvage is not None:
        return _salvaged(data, sections, ids, by_seq, salvage)
    if problems:
        raise _Problems(problems)
    return claims


def _salvaged(data: dict, sections: set[str], ids: set[str], by_seq: dict[str, str],
              notes: list[str]) -> list[Claim]:
    """The usable part of a second unusable claims reply: one bad scene id
    in 180 claims shouldn't lose the pass (Eighty Days cited
    `fix-drugs-passepartout-in-opium-den`, which isn't a scene). Unknown ids
    are dropped and the rest kept, up to the limit; a claim left with no
    scene is kept with none, so it is reported `unchecked`; a claim from no
    known document or with no text is dropped. What was done goes in `notes`."""
    claims, dropped_ids, no_scene, dropped = [], 0, 0, 0
    for c in data['claims']:
        if not isinstance(c, dict):
            dropped += 1
            continue
        sec, text = str(c.get('section', '')).strip(), str(c.get('claim', '')).strip()
        if sec not in sections or not text:
            dropped += 1
            continue
        raw = c.get('scenes') if isinstance(c.get('scenes'), list) else []
        cited = [str(x).strip() for x in raw if str(x).strip()]
        cited = [x if x in ids else by_seq.get(x, x) for x in cited]
        kept = [x for x in cited if x in ids][:MAX_SCENES_PER_CLAIM]
        dropped_ids += len([x for x in cited if x not in ids])
        no_scene += not kept
        kind = c.get('kind') if c.get('kind') in KINDS else 'event'
        claims.append(Claim(sec, kind, text, kept))
    notes.append(f'claims reply still had problems after a retry; kept {len(claims)} '
                 f'claim(s): {dropped_ids} unknown scene id(s) dropped, {no_scene} claim(s) '
                 f'left with no scene (unchecked), {dropped} claim(s) dropped')
    return claims


def anchor_claims(tiers: Tiers, scenes: list[dict[str, str]]) -> list[Claim]:
    """Each architecture anchor's summary, as a claim about its own scene."""
    ids = {r['id'] for r in scenes}
    return [Claim(f'architecture:{r["id"]}', 'event', r.get('summary', '').strip(), [r['id']])
            for r in tiers.architecture
            if r.get('summary', '').strip() and r['id'] in ids]


# ---------------------------------------------------------------------------
# Pass 2: verify
# ---------------------------------------------------------------------------

def batches(claims: list[Claim], words: dict[str, int],
            budget: int = BATCH_WORDS, max_claims: int = BATCH_CLAIMS) -> list[list[int]]:
    """Claim indexes grouped so each group's scenes stay within `budget`
    words (a claim whose own scenes are over it goes alone). Claims are taken
    in the order of their first scene, so neighbours share passages."""
    pos: dict[str, int] = {}
    for sid in words:
        pos.setdefault(sid, len(pos))
    order = sorted(range(len(claims)),
                   key=lambda i: min(pos.get(s, 0) for s in claims[i].scenes))
    groups: list[list[int]] = []
    current: list[int] = []
    scenes_in: set[str] = set()
    for i in order:
        new = scenes_in | set(claims[i].scenes)
        if current and (sum(words.get(s, 0) for s in new) > budget
                        or len(current) >= max_claims):
            groups.append(current)
            current, new = [], set(claims[i].scenes)
        current.append(i)
        scenes_in = new
    if current:
        groups.append(current)
    return groups


def build_verify_prompt(claims: list[Claim], group: list[int], passages: dict[str, str],
                        problems: list[str] | None = None) -> str:
    cited = []
    for i in group:
        for s in claims[i].scenes:
            if s not in cited:
                cited.append(s)
    text = '\n\n'.join(f'=== scene {s} ===\n{passages.get(s) or "(no prose)"}' for s in cited)
    listed = '\n'.join(f'{n}. [{claims[i].section}; {claims[i].kind}; scenes '
                       f'{", ".join(claims[i].scenes)}] {claims[i].claim}'
                       for n, i in enumerate(group, 1))
    return f"""Check each claim about a book against the passages from that book below.

Judge only from these passages. Something true of the story elsewhere, in
another telling or in what you know of it, but not shown here is `not_shown`.

- `supported`: the passages show it, as stated.
- `contradicted`: the passages show something different: another person, cause,
  order or outcome, or a process told as one moment when the passages show it
  happening by degrees ("all", "finally", "the last").
- `not_shown`: the passages neither show it nor rule it out.
- `overreach`: an interpretation the passages contradict or give no ground
  for, or one that belongs to another work or tradition rather than this text.

An interpretation (a theme, a motive, what something costs or means) is
rarely stated outright: it is `supported` when the passages show what it rests
on, even if no sentence says it. A logline or synopsis compresses: judge what
it claims happened, not its emphasis or wording.

## Passages

{text}

## Claims

{listed}
{_retry_block(problems)}
## Answer

`verdicts`: one per claim, by its number `n`. `evidence` quotes the passage
the verdict rests on (a few words, exactly as written), or is empty for
`not_shown`. `correction` says what the text shows instead; empty when
`supported`."""


def parse_verdicts(reply: str, count: int) -> list[dict]:
    from .extract import _json_answer
    data = _json_answer(reply, VERDICTS_SCHEMA)
    by_n: dict[int, dict] = {}
    problems = []
    for v in data['verdicts']:
        if not isinstance(v, dict):
            problems.append(f'a verdict is not an object: {v!r:.60}')
            continue
        n = v.get('n')
        if v.get('verdict') not in VERDICTS:
            problems.append(f'claim {n!r}: verdict {v.get("verdict")!r} is not one of '
                            + ', '.join(VERDICTS))
        if isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= count:
            problems.append(f'verdict for claim {n!r}, which is not in the list')
        elif n in by_n:
            problems.append(f'claim {n} has two verdicts')
        else:
            by_n[n] = v
    missing = [n for n in range(1, count + 1) if n not in by_n]
    if missing:
        problems.append('no verdict for claim(s) ' + ', '.join(map(str, missing)))
    if problems:
        raise _Problems(problems)
    return [by_n[n] for n in range(1, count + 1)]


# ---------------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------------

def _ask(prompt_for: Callable, parse: Callable, schema: dict, model: str, log_file: str,
         max_tokens: int, on_usage: Callable | None, label: str,
         salvage: Callable | None = None):
    """One structured call, retried once with the parser's problems. With
    `salvage`, a second reply that still has problems is read by it instead
    of failing the pass."""
    from .api import extract_text, invoke_to_file, is_truncated
    problems = None
    for attempt in (1, 2):
        path = log_file.replace('.json', f'-{attempt}.json')
        try:
            response = invoke_to_file(prompt_for(problems), model, path, max_tokens,
                                      label=label, output_schema=schema)
        except RuntimeError as e:
            raise FidelityError(f'{label}: the API call failed ({e})') from e
        if on_usage:
            on_usage(path, label)
        if is_truncated(response):
            raise FidelityError(f'{label}: the reply hit its token limit')
        try:
            return parse(extract_text(response))
        except _Problems as e:
            if attempt == 2:
                if salvage is not None:
                    log(f'  WARNING: {label}: still {len(e.problems)} problem(s) after a retry; '
                        'keeping what can be used')
                    return salvage(extract_text(response))
                raise FidelityError(f'{label}: still unusable after a retry: {e}') from e
            log(f'  {label}: {len(e.problems)} problem(s) in the reply; asking once more')
            problems = e.problems
        except ValueError as e:
            raise FidelityError(f'{label}: unreadable reply ({e})') from e
        except (KeyError, TypeError, AttributeError) as e:
            raise FidelityError(f'{label}: malformed reply ({type(e).__name__}: {e})') from e
    raise AssertionError('unreachable')


def forecast_claims(tiers: Tiers, scenes: list[dict[str, str]], model: str) -> float:
    from .costs import _get_price
    total = 0.0
    for docs in (tiers.summary_docs(), tiers.story_architecture):
        if docs:
            words = len(build_claims_prompt(docs, scenes).split())
            total += (words * 1.3 * _get_price(model, 'input')
                      + CLAIMS_OUTPUT_TOKENS / 2 * _get_price(model, 'output')) / 1_000_000
    return total


def forecast_verify(groups: list[list[int]], claims: list[Claim], words: dict[str, int],
                    model: str) -> float:
    from .costs import _get_price
    total_in = total_out = 0
    for g in groups:
        cited = {s for i in g for s in claims[i].scenes}
        total_in += (sum(words.get(s, 0) for s in cited) + 60 * len(g) + 400) * 1.3
        total_out += 90 * len(g)
    return (total_in * _get_price(model, 'input')
            + total_out * _get_price(model, 'output')) / 1_000_000


def run(project_dir: str, model: str, *, log_dir: str,
        approve: Callable[[float], bool] = lambda cost: True,
        on_usage: Callable | None = None) -> Result:
    """Both passes. `approve(cost)` is asked before the verify pass with its
    forecast (the claims pass is forecast by the caller). Raises
    FidelityError when a pass can't finish."""
    tiers = read_tiers(project_dir)
    scenes = _scenes(project_dir)
    result = Result()
    if tiers.empty():
        raise FidelityError('no upper tiers to check (story-summary.md is the template, '
                            'and spine.csv and architecture.csv are empty)')
    os.makedirs(log_dir, exist_ok=True)

    claims: list[Claim] = []
    for label, docs, every in (('claims', tiers.summary_docs(), True),
                               ('claims-architecture', tiers.story_architecture, False)):
        if not docs:
            continue
        log(f'  Pass 1: splitting {"story-architecture.md" if not every else "the summary and spine"} '
            'into claims...')
        claims += _ask(lambda p, d=docs: build_claims_prompt(d, scenes, p),
                       lambda r, d=docs, e=every: parse_claims(r, d, scenes, e),
                       CLAIMS_SCHEMA, model, os.path.join(log_dir, f'text-fidelity-{label}.json'),
                       CLAIMS_OUTPUT_TOKENS, on_usage, f'text-fidelity-{label}',
                       salvage=lambda r, d=docs, e=every: parse_claims(
                           r, d, scenes, e, salvage=result.notes))
    claims += anchor_claims(tiers, scenes)
    log(f'  {len(claims)} claim(s)')

    words = {r['id']: len(_prose(project_dir, r['id']).split()) for r in scenes}
    no_prose = [i for i, c in enumerate(claims) if not any(words.get(s) for s in c.scenes)]
    for i in no_prose:
        claims[i].verdict = UNCHECKED
    if no_prose:
        result.notes.append(f'{len(no_prose)} claim(s) cite only scenes with no prose; '
                            'not checked')
    todo = [i for i in range(len(claims)) if i not in set(no_prose)]
    groups = [[todo[j] for j in g] for g in batches([claims[i] for i in todo], words)]
    cost = forecast_verify(groups, claims, words, model)
    log(f'  Pass 2: {len(groups)} call(s) to check them against the prose, ~${cost:.2f} ({model})')
    if not approve(cost):
        raise FidelityError('the verify pass was declined (cost threshold)')
    passages = {sid: _prose(project_dir, sid) for g in groups for i in g
                for sid in claims[i].scenes}
    for k, g in enumerate(groups, 1):
        try:
            verdicts = _ask(lambda p, g=g: build_verify_prompt(claims, g, passages, p),
                            lambda r, g=g: parse_verdicts(r, len(g)), VERDICTS_SCHEMA, model,
                            os.path.join(log_dir, f'text-fidelity-verify-{k}.json'),
                            VERIFY_OUTPUT_TOKENS, on_usage, 'text-fidelity-verify')
        except FidelityError as e:
            # The other batches' verdicts are paid for: keep them, and say
            # which claims this one leaves unchecked
            log(f'  WARNING: batch {k} of {len(groups)} not checked: {e}')
            result.notes.append(f'batch {k} ({len(g)} claims) not checked: {e}')
            for i in g:
                claims[i].verdict = UNCHECKED
            continue
        for i, v in zip(g, verdicts):
            claims[i].verdict = v['verdict']
            claims[i].evidence = str(v.get('evidence', '')).strip()
            claims[i].correction = str(v.get('correction', '')).strip()
    result.claims = claims
    return result


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def _group_of(section: str) -> str:
    return section.split(':', 1)[0]


def write(result: Result, out_dir: str, title: str = '') -> None:
    os.makedirs(out_dir, exist_ok=True)
    # Pipe CSV as the project writes it (`extract_describe._cell`: one line, no
    # `|`, unquoted, a leading `"` made `“` so csv.DictReader reads it back)
    from .extract_describe import _cell as csv_safe
    with open(os.path.join(out_dir, 'claims.csv'), 'w', encoding='utf-8') as f:
        f.write('|'.join(CLAIM_COLUMNS) + '\n')
        for n, c in enumerate(result.claims, 1):
            f.write('|'.join([str(n), c.section, c.kind, csv_safe(c.claim), ';'.join(c.scenes),
                              c.verdict, csv_safe(c.evidence), csv_safe(c.correction)]) + '\n')
    with open(os.path.join(out_dir, 'report.md'), 'w', encoding='utf-8') as f:
        f.write(render_report(result, title))
    result.output_dir = out_dir


def counts(claims: list[Claim]) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for c in claims:
        row = out.setdefault(_group_of(c.section), {v: 0 for v in (*VERDICTS, UNCHECKED)})
        row[c.verdict] = row.get(c.verdict, 0) + 1
    return out


def render_report(result: Result, title: str = '') -> str:
    claims = result.claims
    lines = [f'# Text fidelity{": " + title if title else ""}', '',
             f'{len(claims)} claims from the upper tiers, each checked against the prose '
             f'of the scenes it cites. Cost ${result.cost:.2f}.', '',
             '| tier | supported | contradicted | overreach | not shown | unchecked |',
             '|---|---|---|---|---|---|']
    order = ['logline', 'synopsis', 'act-shape', 'theme', 'spine', 'architecture',
             'story-architecture']
    table = counts(claims)
    for g in order:
        if g in table:
            r = table[g]
            lines.append(f'| {g} | {r["supported"]} | {r["contradicted"]} | {r["overreach"]} '
                         f'| {r["not_shown"]} | {r[UNCHECKED]} |')
    for verdict, heading in (('contradicted', 'Contradicted by the text'),
                             ('overreach', 'Readings the text does not bear out'),
                             ('not_shown', 'Not shown in the cited scenes')):
        found = [c for c in claims if c.verdict == verdict]
        if not found:
            continue
        lines += ['', f'## {heading} ({len(found)})', '']
        for c in found:
            lines.append(f'- **{c.section}** ({c.kind}; {", ".join(c.scenes)}): {c.claim}')
            if c.evidence:
                lines.append(f'  - text: "{c.evidence}"')
            if c.correction:
                lines.append(f'  - instead: {c.correction}')
    if result.notes:
        lines += ['', '## Notes', ''] + [f'- {n}' for n in result.notes]
    return '\n'.join(lines) + '\n'


def output_dir(project_dir: str) -> str:
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    return os.path.join(project_dir, 'working', 'scores', 'text-fidelity', stamp)
