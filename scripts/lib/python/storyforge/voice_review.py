"""The voice review: one agent finds the problems, another rewrites them
(#655; Ben, 2026-11-14).

*Wrath Like Smoke*'s voice rounds showed that writing from a list of things
to avoid makes flat prose (round 3 obeyed every flagged problem and read
"flat and listless"). So the list, `reference/voice/checks.md`, is only ever
read by a **reviewer**, on a finished scene. It flags lines: the words, the
check, why. A **reviser**, in a fresh context, gets the voice (book.md and
the anchors, `voice_book.resolve`) and the flagged lines with what's wrong
with each, never the list, and rewrites only those lines toward the anchors.

Code keeps both honest:

- A flag whose quote isn't in the scene (`quotes.quote_in`) is dropped and
  said (`Review.unverified`).
- An edit must replace words that occur once in the scene, inside the
  sentence its flag quotes (`sentence_spans`; whitespace loosened within a
  paragraph, `scene_layout.find_span`); any other edit is dropped and
  said (`Revision.dropped`). Edits that overlap are dropped together. So the
  reviser can't touch a line nobody flagged.
- The reviser may keep a flagged line as it is, saying why
  (`Revision.kept`): the reviewer can be wrong.

The author's own marks go to the same reviser (`flags_from_marks`): a mark
asking for a change is a `Flag` whose `source` is `AUTHOR`; a keep (a line
that works) is shown as an example and never edited. Only `flags_from_marks`
makes an author flag: a reviewer's `check` can't claim it.

`record` writes what happened to `working/voice-reviews/<scene>.md`, for the
author to read. Nothing here commits.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field

from storyforge import voice_book
from storyforge.quotes import normalize, quote_in

REVIEWS_DIR = os.path.join('working', 'voice-reviews')
#: the reviewer's flags per scene, at most
MAX_FLAGS = 12
#: `Flag.source`s: the reviewer flagged it, or the author marked it
REVIEWER, AUTHOR = 'review', 'author'

REVIEW_SCHEMA = {
    'type': 'object',
    'properties': {'flags': {'type': 'array', 'items': {
        'type': 'object',
        'properties': {'quote': {'type': 'string'}, 'check': {'type': 'string'},
                       'why': {'type': 'string'}},
        'required': ['quote', 'check', 'why'],
        'additionalProperties': False,
    }}},
    'required': ['flags'],
    'additionalProperties': False,
}

REVISE_SCHEMA = {
    'type': 'object',
    'properties': {
        'edits': {'type': 'array', 'items': {
            'type': 'object',
            'properties': {'flag': {'type': 'integer'}, 'find': {'type': 'string'},
                           'replace': {'type': 'string'}},
            'required': ['flag', 'find', 'replace'],
            'additionalProperties': False,
        }},
        'kept': {'type': 'array', 'items': {
            'type': 'object',
            'properties': {'flag': {'type': 'integer'}, 'why': {'type': 'string'}},
            'required': ['flag', 'why'],
            'additionalProperties': False,
        }},
    },
    'required': ['edits', 'kept'],
    'additionalProperties': False,
}


class VoiceReviewError(RuntimeError):
    """A review or revision call failed, was cut off or didn't answer in its
    schema; the message says which scene and why."""


@dataclass(frozen=True)
class Flag:
    """A line to look at: the scene's words, the check it matches (a
    check's name or number from checks.md; '' for the author's mark), why,
    and who flagged it (`REVIEWER` or `AUTHOR`)."""
    quote: str
    check: str
    why: str
    source: str = REVIEWER


@dataclass
class Review:
    """The reviewer's flags whose quotes are in the scene; the ones that
    weren't (`unverified`, dropped); how many past `MAX_FLAGS`
    (`over_cap`); and how many repeated a quote already flagged
    (`repeated`)."""
    flags: list[Flag] = field(default_factory=list)
    unverified: list[Flag] = field(default_factory=list)
    over_cap: int = 0
    repeated: int = 0


@dataclass
class Outcome:
    """What became of one flag: the edits applied to it (find, replace),
    why it was kept as it is ('' when not), and why code refused its edits."""
    edits: list[tuple[str, str]] = field(default_factory=list)
    kept: str = ''
    refused: list[str] = field(default_factory=list)

    @property
    def rewritten(self) -> bool:
        return bool(self.edits)


@dataclass
class Revision:
    """What the reviser did: the prose after it, one `Outcome` per flag (in
    the flags' order), and what code dropped that names no flag."""
    prose: str
    outcomes: list[Outcome] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)

    @property
    def rewritten(self) -> int:
        """How many flagged lines were rewritten (not how many edits)."""
        return sum(o.rewritten for o in self.outcomes)

    @property
    def kept(self) -> int:
        return sum(bool(o.kept) and not o.rewritten for o in self.outcomes)

    @property
    def refused(self) -> int:
        return sum(bool(o.refused) and not o.rewritten for o in self.outcomes)

    @property
    def untouched(self) -> int:
        """Flags the reviser neither edited nor kept, and code refused nothing for."""
        return sum(not (o.edits or o.kept or o.refused) for o in self.outcomes)

    def summary(self) -> str:
        parts = [f'{self.rewritten} line(s) rewritten']
        if self.kept:
            parts.append(f'{self.kept} kept')
        if self.refused:
            parts.append(f'{self.refused} whose edits were refused')
        if self.untouched:
            parts.append(f'{self.untouched} not answered')
        return ', '.join(parts)


# ============================================================================
# Sentences
# ============================================================================

# the splitter is the scene layout's (re-exported: the reviser's scope is a sentence)
from storyforge.scene_layout import sentence_spans  # noqa: E402


def flag_spans(prose: str, quote: str) -> list[tuple[int, int]]:
    """The span (start, end) the flag covers: the sentences its quote is
    in. An exact match covers the sentences it touches; otherwise the
    sentences (one, or two running on) whose words hold the quote. [] when
    the quote isn't in the scene."""
    spans = sentence_spans(prose)
    at = prose.find(quote.strip()) if quote.strip() else -1
    if at >= 0:
        end = at + len(quote.strip())
        hit = [s for s in spans if s[0] < end and at < s[1]]
        return [(hit[0][0], hit[-1][1])] if hit else []
    for i, (a, b) in enumerate(spans):
        if quote_in(prose[a:b], quote):
            return [(a, b)]
        if i + 1 < len(spans) and quote_in(prose[a:spans[i + 1][1]], quote):
            return [(a, spans[i + 1][1])]
    return []


# ============================================================================
# The reviewer
# ============================================================================

REVIEW_PROMPT = """You review one scene of a novel against the author's checks. The checks are problems the author has marked in drafts before, each with an example. The voice the scene should have is shown first: passages the author chose, and notes on what they do.

Read the scene line by line. Flag a line only when it matches one of the checks: quote the fewest exact words from the scene that show it, name the check (its number or title), and say in one sentence what is wrong here. Don't flag what is merely different from your taste: the passages are the standard, and a line that works the way they work is fine. Don't rewrite anything. Flag at most {max_flags} lines, the clearest first. If nothing matches, return no flags.

{voice}

## The checks

{checks}

## Scene {scene_id}

{prose}"""


def build_review_prompt(scene_id: str, prose: str, voice: str, checks: str) -> str:
    return REVIEW_PROMPT.format(max_flags=MAX_FLAGS, voice=voice, checks=checks,
                                scene_id=scene_id, prose=prose)


def parse_review(text: str, prose: str) -> Review:
    """The reviewer's reply, its flags checked against the scene.

    Raises:
        ValueError: the reply isn't the schema.
    """
    data = json.loads(text)
    out = Review()
    seen = set()
    for item in data['flags']:
        # always the reviewer's: a `check` naming the author claims nothing
        flag = Flag(str(item['quote']).strip(), str(item['check']).strip(),
                    str(item['why']).strip(), REVIEWER)
        key = normalize(flag.quote)
        if not flag.quote:
            continue
        if key in seen:
            out.repeated += 1
            continue
        seen.add(key)
        if not flag_spans(prose, flag.quote):
            out.unverified.append(flag)
        elif len(out.flags) >= MAX_FLAGS:
            out.over_cap += 1
        else:
            out.flags.append(flag)
    return out


def review(project_dir: str, scene_id: str, prose: str, *, model: str,
           log_file: str = '') -> Review:
    """The reviewer's flags for `prose`, or an empty review when the book
    has no checks.md (said by the caller: `voice_book.checks_text`).

    Raises:
        VoiceReviewError: the call failed, was cut off or isn't the schema.
        common.ReferenceDocError: checks.md or the voice can't be read.
    """
    checks = voice_book.checks_text(project_dir)
    if not checks:
        return Review()
    voice = voice_book.resolve(project_dir)
    voice.raise_if_unreadable(project_dir)
    text = _call(build_review_prompt(scene_id, prose, voice.text if voice.kind == 'ok' else '',
                                     checks),
                 model, REVIEW_SCHEMA, f'voice review {scene_id}', log_file, 6000, scene_id,
                 project_dir)
    try:
        return parse_review(text, prose)
    except (ValueError, KeyError, TypeError) as e:
        raise VoiceReviewError(f'{scene_id}: the voice review\'s reply could not be read '
                               f'({e})') from e


# ============================================================================
# The reviser
# ============================================================================

REVISE_PROMPT = """You revise flagged lines in one scene of a novel so they read like the voice shown below: passages the author chose, and notes on what they do. Each flag quotes words from the scene and says what is wrong there.

For each flag, either edit the sentence it quotes or keep it:
- An edit replaces `find`, words copied exactly from the scene that occur in it once and lie inside the flagged sentence, with `replace`. Keep `find` to the sentence or clause that changes. Edits must not overlap.
- Write toward the passages. Often the fix is to cut: a tail after the sentence has landed, a line that explains the one before it. Keep what happens, who does it and every fact; change how it is said.
- Change nothing that isn't flagged.
- If a flag is wrong (the line already works the way the passages work), keep the line and say why in one sentence.

`flag` is the flag's number.

{voice}{keeps}

## Flags

{flags}

## Scene {scene_id}

{prose}"""


def build_revise_prompt(scene_id: str, prose: str, voice: str, flags: list[Flag],
                        keeps: list[str] | tuple = ()) -> str:
    listing = '\n'.join(
        f'{n}. "{f.quote}": {f.why}' + (' (the author\'s note)' if f.source == AUTHOR else '')
        for n, f in enumerate(flags, start=1))
    keep_block = ''
    if keeps:
        keep_block = ('\n\n## Lines in this scene the author marked as working\n\n'
                      'Write toward these too. They aren\'t flags: never edit them.\n\n'
                      + '\n'.join(f'- "{k}"' for k in keeps))
    return REVISE_PROMPT.format(voice=voice, keeps=keep_block, flags=listing,
                                scene_id=scene_id, prose=prose)


def apply_revision(prose: str, flags: list[Flag], reply: dict,
                   protected: list[str] | tuple = (), layout: bool = True) -> Revision:
    """The reviser's edits applied to `prose`, each only inside its flag's
    sentence and never touching a `protected` line (the author's keeps);
    one `Outcome` per flag. A flag both edited and kept counts as edited
    (the keep is noted in `dropped`). `layout`: the paragraphs edited are
    laid out a sentence per line (`gate.apply_edits`); False for a voice
    sample, which keeps its own layout."""
    from storyforge.gate import GateError, apply_edits
    from storyforge.scene_layout import find_span
    out = Revision(prose, [Outcome() for _ in flags])
    keep_spans = [span for k in protected for span in flag_spans(prose, k)]
    ok: list[tuple[int, dict, tuple[int, int]]] = []
    for e in reply.get('edits', []):
        n, find = e.get('flag'), e.get('find') or ''
        if not isinstance(n, int) or not 1 <= n <= len(flags):
            out.dropped.append(f'an edit names flag {n!r}, which there isn\'t')
            continue
        refused = out.outcomes[n - 1].refused
        found = find_span(prose, find)
        span = found.span
        if span is None:
            refused.append(f'its edit\'s words occur {found.problem(find)}')
            continue
        allowed = flag_spans(prose, flags[n - 1].quote)
        if not any(a <= span[0] and span[1] <= b for a, b in allowed):
            refused.append(f'its edit reaches outside the flagged sentence: {find[:80]!r}')
            continue
        if any(span[0] < b and a < span[1] for a, b in keep_spans):
            refused.append(f'its edit touches a line the author marked keep: {find[:80]!r}')
            continue
        ok.append((n, e, span))
    ok.sort(key=lambda t: t[2])
    clash = {i for i in range(len(ok) - 1) if ok[i + 1][2][0] < ok[i][2][1]}
    clash |= {i + 1 for i in clash}
    for i in sorted(clash):
        out.outcomes[ok[i][0] - 1].refused.append('its edit overlaps another')
    ok = [t for i, t in enumerate(ok) if i not in clash]
    try:
        out.prose = apply_edits(prose, [e for _, e, _ in ok], layout=layout)
    except GateError as e:   # checked above; said if it ever happens
        out.dropped.append(f'the edits could not be applied ({e})')
        ok = []
    for n, e, _ in ok:
        out.outcomes[n - 1].edits.append((e['find'], e.get('replace') or ''))
    for k in reply.get('kept', []):
        n = k.get('flag')
        if not isinstance(n, int) or not 1 <= n <= len(flags):
            out.dropped.append(f'a keep names flag {n!r}, which there isn\'t')
            continue
        o = out.outcomes[n - 1]
        why = str(k.get('why', '')).strip() or '(no reason given)'
        if o.edits:
            out.dropped.append(f'flag {n} was both edited and kept ({why}): the edit stands')
        else:
            o.kept = why
    return out


def revise(project_dir: str, scene_id: str, prose: str, flags: list[Flag], *, model: str,
           log_file: str = '', keeps: list[str] | tuple = (), layout: bool = True) -> Revision:
    """`prose` with the flagged lines rewritten toward the voice; `keeps`
    (the author's lines that work) are shown as examples and protected.
    `layout`: as `apply_revision` (False for a voice sample).

    Raises:
        VoiceReviewError: the call failed, was cut off or isn't the schema.
        common.ReferenceDocError: the voice can't be read.
    """
    if not flags:
        return Revision(prose)
    voice = voice_book.resolve(project_dir)
    voice.raise_if_unreadable(project_dir)
    text = _call(build_revise_prompt(scene_id, prose, voice.text if voice.kind == 'ok' else '',
                                     flags, keeps),
                 model, REVISE_SCHEMA, f'voice revise {scene_id}', log_file, 8000, scene_id,
                 project_dir)
    try:
        reply = json.loads(text)
        if not isinstance(reply.get('edits'), list) or not isinstance(reply.get('kept'), list):
            raise ValueError('edits and kept must be lists')
    except (ValueError, AttributeError) as e:
        raise VoiceReviewError(f'{scene_id}: the reviser\'s reply could not be read ({e})') from e
    return apply_revision(prose, flags, reply, protected=keeps, layout=layout)


def flags_from_marks(marks) -> list[Flag]:
    """The author's marks asking for a change, (the scene's words, the
    note), as flags for the reviser (keeps are `marks.SceneMarks.keeps`)."""
    return [Flag(m[0].strip(), '', m[1].strip(), AUTHOR) for m in marks if m[0].strip()]


# ============================================================================
# The record
# ============================================================================

def record(project_dir: str, scene_id: str, rev: Review, revision: Revision | None,
           notes: list[str] | tuple = ()) -> str:
    """Write what the review found and what was done to
    `working/voice-reviews/<scene>.md` (replacing an earlier one). Returns
    its path, relative to the project. `revision` None: the reviser didn't
    run (no flag, or it failed: `notes` say which)."""
    lines = [f'# Voice review: {scene_id}', '']
    lines += [f'NOTE: {n}' for n in notes]
    if notes:
        lines.append('')
    if not rev.flags:
        lines.append('No line was flagged.')
    outcomes = revision.outcomes if revision else []
    for n, f in enumerate(rev.flags, start=1):
        who = 'the author' if f.source == AUTHOR else f'check {f.check}'
        lines += [f'## {n}. {who}', '', f'> {f.quote}', '', f.why, '']
        o = outcomes[n - 1] if n - 1 < len(outcomes) else None
        if o is None:
            continue
        for a, b in o.edits:
            lines += ['Rewritten:', '', f'- before: {a}', f'- after: {b or "(cut)"}', '']
        if o.kept and not o.edits:
            lines += [f'Kept: {o.kept}', '']
        for why in o.refused:
            lines += [f'Edit refused: {why}', '']
        if not (o.edits or o.kept or o.refused):
            lines += ['Not changed (the reviser gave no edit and no reason).', '']
    if rev.unverified:
        lines += ['## Flags left out (their words aren\'t in the scene)', '']
        lines += [f'- "{f.quote}" ({f.check or f.source}): {f.why}' for f in rev.unverified]
        lines.append('')
    if rev.over_cap:
        lines += [f'{rev.over_cap} more flag(s) past the cap of {MAX_FLAGS} were left out.', '']
    if rev.repeated:
        lines += [f'{rev.repeated} flag(s) repeating a quote already flagged were left out.',
                  '']
    if revision and revision.dropped:
        lines += ['## Left out', ''] + [f'- {d}' for d in revision.dropped] + ['']
    rel = os.path.join(REVIEWS_DIR, f'{scene_id}.md')
    path = os.path.join(project_dir, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(lines).rstrip() + '\n')
    return rel


def _call(prompt: str, model: str, schema: dict, label: str, log_file: str, tokens: int,
          scene_id: str, project_dir: str = '') -> str:
    from storyforge.api import RefusalError, extract_text, invoke, is_truncated, log_reply
    try:
        response = invoke(prompt, model, tokens, label=label, output_schema=schema)
        if project_dir:
            log_reply(project_dir, response, 'voice-review', scene_id, model)
    except RefusalError as e:
        raise VoiceReviewError(f'{scene_id}: {label} was refused ({e})') from e
    except RuntimeError as e:
        raise VoiceReviewError(f'{scene_id}: {label} failed ({e})') from e
    if log_file:
        os.makedirs(os.path.dirname(log_file) or '.', exist_ok=True)
        with open(log_file, 'w', encoding='utf-8') as f:
            json.dump(response, f)
    if is_truncated(response):
        raise VoiceReviewError(f'{scene_id}: {label}\'s reply hit its token limit')
    return extract_text(response)
