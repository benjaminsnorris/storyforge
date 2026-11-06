"""The gate: nothing commits to the ledger without a check (rethink plan §3.2).

For one scene's prose, `gate_scene` runs:

1. **Extract** the scene's commitments with phase 4's rubric
   (`extract.build_commitments_prompt`), offered the facts in force entering
   it and the registry facts recorded for it (`extract.known_for_scene`),
   then ask of each whether it lasts beyond the scene
   (`persistence.judge`): one that doesn't is not proposed (`dropped`,
   reported).
2. **Halt** on decision 2's immediate tier: `audit.halting_conditions` on the
   proposed rows (a `fixed` fact superseded or changed). The third trigger,
   a fact extraction flagged low-confidence, is not wired: phase 4's schema
   has no confidence yet (adding it re-records E3 and E5). A contradiction
   with the plan is the checker's to find (step 3), not extraction's
   (Ben, 2026-10-30): extraction marks added detail as superseding a
   registry fact, and a registry `resolves` is the author's estimate, so a
   `supersedes` or `ends` it proposes on a registry fact is not applied:
   it goes to the checker as a dispute to rule on (a contradiction, or
   cleared), and one it doesn't rule on blocks the commit.
3. **Check** the scene against the book and its brief (`checker.check_scene`):
   contradictions and broken promises, by code. `GATE_READINGS` (2)
   independent readings, their union: each reading misses real errors
   another finds. Measured (E8, E4, 2026-11-01): stricter, not more
   convergent (a re-check after the fix still finds things neither first
   reading did), and no gain yet in E4's errors committed.
4. **Commit** only when nothing halted, extraction left nothing unresolved
   (`UNRESOLVED`: a quote not in the scene, a `supersedes` or `ends` that
   names nothing it can apply to), and the check found nothing, verified or
   not, other than contradictions already in the book before the pass
   (`gate_scene(before=)`: `inherited`, reported as `ALREADY IN THE SCENE`
   and kept in working/gate-reported.csv; the commitments stating them are
   held back): the
   scene's commitments replace its earlier ones (`introduced_by` = the
   command that wrote the prose), each registry fact the prose was found to
   establish gets its blank quote filled (`ledger.fill_quote`), and the
   ledger is saved through `ledger.save`, so the audit log has every fact.
5. **Re-check** (Phase 4, `docs/plans/2026-10-31-phase4-safe-revision-design.md`):
   a fact restated keeps its id; the later scenes depending on what the
   scene dropped or changed are listed `RECHECK`, and `recheck_pending`
   re-gates them in reading order (report and stop, under the cost
   threshold). The caller runs it once the scene is committed.

**Fix** (plan §3.2 step 3) is the caller's: a result that didn't pass names
what to fix. The caller must also report `result.problems`' report-only
kinds (`REPORTED`) and `result.inherited` on a pass (`report_lines` has both): they don't make the ledger wrong, but the
author should know. The design is `docs/plans/2026-10-30-gate-ledger-design.md`.

Fails loud: a step that can't finish raises `GateError`, and nothing is
written. A result that didn't pass writes nothing either; it is not an
exception, because the caller decides between fixing and reporting
(advisor mode).
"""

from __future__ import annotations

import copy
import os
import re
from dataclasses import dataclass, field
from typing import NamedTuple

from storyforge import audit, ledger, persistence
from storyforge.checker import (GATE_READINGS, CheckError, CheckResult, Dispute, Finding,
                               check_scene)
from storyforge.extract import MISQUOTE, NO_QUOTE

#: The commands whose prose the gate commits (`ledger.COMMITMENT_WRITERS`
#: without the extract pass)
GATE_COMMANDS = tuple(w for w in ledger.COMMITMENT_WRITERS if w != ledger.COMMITMENTS_PASS)

#: Extraction problems that would commit a wrong row: they block the commit
UNRESOLVED = (MISQUOTE, NO_QUOTE, 'supersedes', 'ends', 'ends again', 'rejected')
#: Extraction problems reported on a pass: a link extraction proposed to a
#: registry fact, not applied (`disagrees`, `ends registry`: the checker
#: judges contradictions with the plan), a subject not in the registries
#: (an object has none), facts left out past the offer cap, facts tied to a
#: scene id that isn't a scene, an `ends` naming a fixed fact (one can't
#: end, so the link is never applied and the row is right without it:
#: G-028, #556, an extraction slip that stopped an unattended run)
REPORTED = ('disagrees', 'ends registry', 'subject', 'cap', 'unplaced', 'ends fixed')
#: What a report line says each `REPORTED` kind means, where its name alone
#: doesn't (#564: `NOTE (cap): scene (62)` said nothing of what was cut)
_REPORTED_LABEL = {
    'cap': 'facts in force left out of what extraction was offered, over the cap '
           '(extract.MAX_KNOWN_COMMITMENTS); the scene\'s people and place kept first',
}
#: Scenes this process's gate runs offered only part of the facts in force,
#: with how many were left out (`prompts.ledger_window_summary`)
OFFER_LEFT_OUT: dict[str, int] = {}


class GateError(RuntimeError):
    """A gate step couldn't finish; nothing was written. From `gate_and_fix`,
    `.first` is the first gate run when there was one, and `.log_dir` the
    invocation's logs (`run_log_dir`)."""
    first: 'GateResult | None' = None
    log_dir: str = ''


def _among(f: Finding, findings: list[Finding]) -> bool:
    """Whether `f` is one of `findings`, by identity: `Finding` compares
    by value, and the classified lists hold the check's own objects."""
    return any(f is g for g in findings)


@dataclass
class GateResult:
    scene_id: str
    #: the scene's commitments, as they would be (or were) committed
    proposed: list[dict[str, str]] = field(default_factory=list)
    halts: list[audit.Halt] = field(default_factory=list)
    #: extraction's problems (`extract.COMMITMENT_PROBLEMS` → strings):
    #: `UNRESOLVED` block the commit; `disagrees` and `ends registry` go to
    #: the checker as disputes; the rest of `REPORTED` are for the caller
    problems: dict[str, list[str]] = field(default_factory=dict)
    check: CheckResult | None = None
    committed: bool = False
    #: registry ids whose quote was filled on commit
    quotes_filled: list[str] = field(default_factory=list)
    #: (statement, why) for each extracted fact the persistence check judged
    #: not to last beyond the scene: not proposed, so never committed
    dropped: list[tuple[str, str]] = field(default_factory=list)
    #: on commit (Phase 4): the scene's earlier commitments this version
    #: dropped or changed, and the earlier states whose end in this scene
    #: came or went
    changed: list[str] = field(default_factory=list)
    #: on commit: the later scenes, with prose, listed pending for a re-check
    #: because their facts depend on `changed` (`recheck_pending` runs it)
    recheck: list[str] = field(default_factory=list)
    #: on commit: changed fact id → why its dependents can't all be found
    #: (`ledger.Dependents.unrelated`), for the caller to report
    unrelated: dict[str, str] = field(default_factory=dict)
    #: on commit: later scenes depending on `changed` that can't be re-checked
    #: (`scene (why)`: no prose yet, cut or merged), for the caller to report
    not_rechecked: list[str] = field(default_factory=list)
    #: on commit: what narrowed the dependents' name match
    #: (`ledger.subject_names`' notes: a missing registry, no id column),
    #: for the caller to report
    name_notes: list[str] = field(default_factory=list)
    #: on commit (#558): why the earlier prose couldn't be diffed (so every
    #: reworded fact counts as changed), or why this prose wasn't recorded
    prose_notes: list[str] = field(default_factory=list)
    #: on commit (#558): the earlier commitments kept as they were, read from
    #: paragraphs the new prose has unchanged and in place (`steady_facts`)
    steady: list[str] = field(default_factory=list)
    #: on commit: registry rows (the author's) whose `supersedes`/`depends_on`
    #: names a commitment this version removed (`row → id`): a re-check
    #: replaces only commitments, so the author must fix the link
    dangling: list[str] = field(default_factory=list)
    #: verified contradictions that were in the book before the pass that
    #: wrote this prose (`_classify`): the author's to fix, reported (and
    #: kept in working/gate-reported.csv on commit) but not blocking, and
    #: never sent to the fix. A subset of `check.findings`, set once
    inherited: list[Finding] = field(default_factory=list)
    #: verified contradictions in the brief's own scripted words
    #: (`_brief_lines`, `_is_plan_conflict`): the brief and the book
    #: disagree, so no prose edit can deliver one without breaking the
    #: other. They block, and go to the author rather than the fix. A subset
    #: of `findings`, disjoint from `inherited`
    plan_conflicts: list[Finding] = field(default_factory=list)
    #: (plan conflict, whether its speaker was checked and why not), for
    #: the report (`_plan_conflict`)
    speaker_notes: list[tuple[Finding, str]] = field(default_factory=list)
    #: on commit: (statement, inherited finding) for each extracted
    #: commitment stating an inherited contradiction, not recorded
    #: (`_hold_back`)
    held_back: list[tuple[str, Finding]] = field(default_factory=list)
    #: (finding, why) for each verified contradiction with an earlier scene
    #: the source backs this scene on (`gate_source`, #557): not blocking,
    #: never sent to the fix; the earlier scene is listed `SOURCE_FIX` on
    #: commit. Disjoint from `inherited` and `plan_conflicts`
    source_backed: list[tuple[Finding, str]] = field(default_factory=list)
    #: (statement, why) for each extracted fact the source contradicts: not
    #: committed (#557, B-027)
    source_dropped: list[tuple[str, str]] = field(default_factory=list)
    #: why the source check didn't run, or what it didn't rule on
    source_notes: list[str] = field(default_factory=list)
    #: on commit: the earlier scenes' commitments marked `superseded`
    #: because the source backs this scene against them (#557's review)
    source_superseded: list[str] = field(default_factory=list)
    #: on commit: source-backed findings whose earlier fact wasn't found
    #: (its commitments are held back instead)
    source_unmatched: list[Finding] = field(default_factory=list)
    #: the source check ruled on every fact new to the scene (#557's third
    #: review: only then can a fix toward the source retire anything)
    source_ruled: bool = False
    #: committed without a pass (`commit_provisional`, `write --keep-going`)
    provisional: bool = False
    #: what `_commit` needs from the run (`_CommitContext`); None until the
    #: run reaches the check
    _ctx: 'object' = field(default=None, repr=False, compare=False)

    @property
    def findings(self) -> list[Finding]:
        """The check's verified findings, less `inherited` and `source_backed`."""
        if not self.check:
            return []
        backed = [f for f, _ in self.source_backed]
        return [f for f in self.check.findings
                if not _among(f, self.inherited) and not _among(f, backed)]

    @property
    def fixable(self) -> list[Finding]:
        """`findings` less `plan_conflicts`: the verified ones the fix is for."""
        return [f for f in self.findings if not _among(f, self.plan_conflicts)]

    @property
    def unverified(self) -> list[Finding]:
        """Findings whose quotes didn't hold up: not shown to be wrong, so
        they block the commit like any other finding."""
        return self.check.unverified if self.check else []

    @property
    def unresolved(self) -> list[str]:
        """Extraction problems that block the commit (`UNRESOLVED`)."""
        return [f'{kind}: {item}' for kind in UNRESOLVED
                for item in self.problems.get(kind, [])]

    @property
    def unruled(self) -> list[Dispute]:
        """Registry facts extraction said the scene changes that the checker
        neither ruled a contradiction nor cleared: they block the commit."""
        return self.check.unruled if self.check else []

    @property
    def passed(self) -> bool:
        return not (self.halts or self.unresolved or self.findings or self.unverified
                    or self.unruled)


def _subjects(project_dir: str) -> dict[str, str]:
    from storyforge.enrich import load_registry_alias_maps
    maps = load_registry_alias_maps(project_dir)
    return {**maps.get('locations', {}), **maps.get('characters', {})}


def _extract(project_dir: str, scene_id: str, prose: str, rows: list[dict[str, str]],
             order: dict[str, int], introduced_by: str, model: str, log_dir: str,
             problems: dict[str, list[str]],
             dropped: list[tuple[str, str]]) -> list[dict[str, str]]:
    from storyforge.api import extract_text, invoke_to_file, is_truncated
    from storyforge.elaborate import get_scene
    from storyforge.enrich import format_registries_for_prompt
    from storyforge.extract import (COMMITMENTS_SCHEMA, build_commitments_prompt,
                                    commitment_rows, known_for_scene,
                                    parse_commitments_response, unplaced_rows)
    ref_dir = os.path.join(project_dir, 'reference')
    scene = get_scene(scene_id, ref_dir) or {}
    subjects = _subjects(project_dir)
    names = ([scene.get('pov', '')] + scene.get('location', '').split(';')
             + scene.get('on_stage', '').split(';'))
    scene_subjects = {subjects[n.strip().lower()] for n in names if n.strip().lower() in subjects}
    known, recorded, left_out = known_for_scene(rows, scene_id, order, scene_subjects)
    OFFER_LEFT_OUT.pop(scene_id, None)   # this run's count, not an earlier gate run's
    if left_out:
        problems['cap'].append(f'{scene_id} ({left_out})')
        OFFER_LEFT_OUT[scene_id] = left_out
    problems['unplaced'].extend(unplaced_rows(rows, order))
    prompt = build_commitments_prompt(
        scene_id, prose, {k: scene.get(k, '') for k in ('title', 'pov', 'location')},
        registries_text=format_registries_for_prompt(project_dir, exclude=('knowledge',)),
        known=known, recorded=recorded)
    log_file = os.path.join(log_dir, f'gate-extract-{scene_id}.json')
    try:
        response = invoke_to_file(prompt, model, log_file, 8000,
                                  output_schema=COMMITMENTS_SCHEMA, label=f'extract {scene_id}')
        if is_truncated(response):
            raise ValueError('the reply hit its token limit')
        found = parse_commitments_response(extract_text(response), scene_id)
    except (RuntimeError, ValueError) as e:   # RefusalError, an API failure, a bad reply
        raise GateError(f'{scene_id}: extraction failed: {e}') from e
    try:
        verdict = persistence.judge(scene_id, prose, found, model=model,
                                    log_file=os.path.join(log_dir,
                                                          f'gate-persistence-{scene_id}.json'))
    except persistence.PersistenceError as e:
        raise GateError(str(e)) from e
    dropped.extend((e['statement'], why) for e, why in verdict.dropped)
    return commitment_rows(verdict.kept, scene_id, prose, rows, known, recorded, subjects,
                           introduced_by, problems, own_writers=ledger.COMMITMENT_WRITERS,
                           registry_is_plan=True)


def _disputes(result: GateResult, rows: list[dict[str, str]]) -> list[Dispute]:
    """Each registry fact extraction says the scene changes, for the
    checker to rule on (Ben, 2026-10-30: the checker decides). From
    `commitment_rows`' problem strings: `disagrees` is `scene: registry-id
    (prose: proposed-id)`, `ends registry` is `scene: registry-id
    (resolves: ...)`."""
    import re
    proposed = {r['id']: r for r in result.proposed}
    out: dict[str, Dispute] = {}
    for item in result.problems.get('disagrees', []):
        m = re.match(r'[^:]+: (\S+) \(prose: (\S+)\)$', item)
        if not m:
            continue
        row = proposed.get(m.group(2), {})
        out.setdefault(m.group(1), Dispute(m.group(1), _statement(rows, m.group(1)),
                                           row.get('quote') or row.get('statement', '')))
    for item in result.problems.get('ends registry', []):
        m = re.match(r'[^:]+: (\S+) \(resolves: ([^)]*)\)$', item)
        if not m:
            continue
        out.setdefault(m.group(1), Dispute(
            m.group(1), _statement(rows, m.group(1)),
            f'the state ends in this scene (the plan says it ends at {m.group(2)})'))
    return list(out.values())


def _statement(rows: list[dict[str, str]], rid: str) -> str:
    return next((r.get('statement', '') for r in rows if r.get('id') == rid), '')


def _words(text: str) -> str:
    """`text` as lowercase words, one space apart, padded: a phrase is
    in it when `_words(phrase)` is a substring."""
    return ' ' + ' '.join(re.findall(r'\w+', text.lower())) + ' '


def _count(words: str) -> int:
    return len(words.split())


#: A quote matched against the scene before the pass needs this many words
#: in all, and each part (split at an ellipsis) `_MIN_PART_WORDS`: a short
#: one ("twelve", "the barn") turns up in old prose by accident (#480's review)
_MIN_QUOTE_WORDS = 4
_MIN_PART_WORDS = 3


def _found_in(quote: str, text: str) -> bool:
    """Whether `quote`'s parts (split at an ellipsis) are in `text`, in
    order, ignoring case, punctuation and spacing; no minimum length."""
    words, at = _words(text), 0
    parts = [p for p in (_words(x) for x in re.split(r'\.\.\.|…', quote)) if p.strip()]
    for p in parts:
        found = words.find(p, at)
        if found < 0:
            return False
        at = found + len(p) - 1
    return bool(parts)


def _quoted_in(quote: str, text: str) -> bool:
    """Whether `quote` is in `text`, ignoring case, punctuation and spacing:
    its parts (split at an ellipsis, as quotes are verified) in order, each
    of `_MIN_PART_WORDS` words or more and `_MIN_QUOTE_WORDS` in all. A
    shorter quote is never found: the safe answer, since a found quote
    makes a finding inherited."""
    parts = [_words(p) for p in re.split(r'\.\.\.|…', quote)]
    parts = [p for p in parts if p.strip()]
    if (not parts or sum(_count(p) for p in parts) < _MIN_QUOTE_WORDS
            or any(_count(p) < _MIN_PART_WORDS for p in parts)):
        return False
    words, at = _words(text), 0
    for p in parts:
        found = words.find(p, at)
        if found < 0:
            return False
        at = found + len(p) - 1   # the next part may start at this one's closing space
    return True


#: The fewest words a brief's own words must have to count as the source of
#: a contradiction: shorter ones ("Yes.") match by accident
_MIN_BRIEF_WORDS = 3


class Scripted(NamedTuple):
    """A phrase the brief scripts (`_brief_lines`), and the character it
    gives the line to, when the brief says (`_label_speaker`)."""
    text: str
    #: the speaker's characters.csv id (its name, for a row with no id);
    #: None: the brief names no one, or not with confidence
    speaker: str | None = None
    #: why `speaker` is None, for the report (`_NO_LABEL` and the rest)
    why: str = 'the brief names no speaker'


#: Why a scripted phrase has no speaker (`Scripted.why`)
_NO_QUOTES = 'the brief line has no quote marks'
_NO_LABEL = 'the brief names no speaker'
_SHARED = 'the brief names a name two characters share'
_UNCLEAR = 'the brief\'s speaker label is not clear'
_NO_CAST = 'no characters in characters.csv'


@dataclass(frozen=True)
class Cast:
    """The characters a speech tag may name (`_cast`, from
    reference/characters.csv)."""
    #: each name, alias and id, as `_words` without the padding → the ids
    #: of the characters it names (more than one: a shared name)
    ids: dict[str, frozenset[str]] = field(default_factory=dict)
    #: id → subject pronoun (`schema.pronoun_key`), only where it is known
    pronouns: dict[str, str] = field(default_factory=dict)
    #: id → name, for the report
    display: dict[str, str] = field(default_factory=dict)
    #: what about the file, or an adaptation's source, keeps speakers from
    #: being checked (WARNINGs)
    warnings: tuple[str, ...] = ()

    @property
    def names(self) -> frozenset[str]:
        return frozenset(self.ids)


def _cast(project_dir: str) -> Cast:
    """The characters (reference/characters.csv): names, aliases and ids,
    and each one's pronouns when the file has a `pronouns` column and the
    cell is one `schema.pronoun_key` reads, or, for an empty cell in an
    adaptation, the imported source's (`source.character_pronouns`). A
    missing file, or one with no named rows, is no one, and a pronoun cell
    that can't be read is unknown, as is a source that can't be read or
    whose value can't be used: each is a `Cast.warnings` line
    (`_warn_once`), since speakers then go unchecked."""
    from storyforge import source
    from storyforge.elaborate import _read_csv
    from storyforge.schema import pronoun_key
    path = os.path.join(project_dir, 'reference', 'characters.csv')
    ids: dict[str, set[str]] = {}
    pronouns: dict[str, str] = {}
    display: dict[str, str] = {}
    warnings: list[str] = []
    try:
        resolved = source.character_pronouns(project_dir)
    except source.SourceError as e:
        resolved = source.CastPronouns()
        warnings.append(f"the source's pronouns can't be read ({e}), so the gate doesn't "
                        f"check a pronoun speech tag of a character with none in "
                        f"characters.csv")
    warnings += [f"{n}: the gate doesn't check those characters' pronoun speech tags"
                 for n in resolved.notes]
    for row in _read_csv(path):
        name = (row.get('name') or '').strip()
        cid = (row.get('id') or '').strip() or name
        if not name:
            continue
        display[cid] = name
        for n in [name, cid, *(row.get('aliases') or '').split(';')]:
            if _words(n).strip():
                ids.setdefault(_words(n).strip(), set()).add(cid)
        key = pronoun_key(row.get('pronouns') or '')
        fallback = resolved.by_id.get(cid)
        if key == '' and fallback and fallback.origin == source.FROM_SOURCE:
            key = pronoun_key(fallback.value)
        elif key == '' and fallback and (fallback.note or fallback.problem):
            warnings.append(f"{name}: no pronouns in characters.csv or from the source "
                            f"({fallback.note or fallback.problem}), so the gate doesn't "
                            f"check a pronoun speech tag on their lines")
        if key:
            pronouns[cid] = key
        elif key is None:
            warnings.append(f"characters.csv: {name}'s pronouns ({row.get('pronouns')!r}) "
                            f"can't be read, so the gate doesn't check a pronoun speech tag "
                            f"on their scripted lines (validate blocks on this)")
    if not ids:
        warnings.insert(0, ('no reference/characters.csv' if not os.path.isfile(path)
                            else 'reference/characters.csv has no named characters')
                        + ': the gate checks no speaker of a scripted line')
    return Cast({n: frozenset(c) for n, c in ids.items()}, pronouns, display, tuple(warnings))


#: WARNING lines already logged in this process (`_warn_once`)
_WARNED: set[str] = set()


def _warn_once(lines) -> None:
    """Log each of `lines` as a WARNING, once per process (a run gates many
    scenes against the same characters.csv)."""
    from storyforge.common import log
    for line in lines:
        if line not in _WARNED:
            _WARNED.add(line)
            log(f'WARNING: {line}')


#: Words in a brief's speaker label that mean someone else in it speaks
#: (`Silas turns to Croy, who says:`)
_LABEL_SPEECH = frozenset('said says asked asks answered answers replied replies told tells '
                          'called calls whispered whispers murmured murmurs muttered mutters '
                          'shouted shouts added adds repeated repeats who'.split())


def _name_at(words: list[str], i: int, cast: Cast) -> tuple[int, frozenset[str]]:
    """The longest name (up to `_MAX_NAME_WORDS` words) in `cast` starting
    at `words[i]`: its length and ids, or (0, empty)."""
    for n in range(min(_MAX_NAME_WORDS, len(words) - i), 0, -1):
        found = cast.ids.get(' '.join(words[i:i + n]))
        if found:
            return n, found
    return 0, frozenset()


def _named(text: str, cast: Cast) -> tuple[str | None, str]:
    """The one character a speaker label (`text`) names, and why not
    (`Scripted.why`) when it names none with confidence: it must start
    with a name or alias (`_name_at`) that only one character has, not a
    possessive ("Lena's warning" may be about someone else's line), not
    with another name next to it (`Thomas and Elena`, `Silas, Croy`), and
    no other name or pronoun later in it may come with a speech verb or
    "who" (`Silas turns to Croy, who says`)."""
    words = _words(text).split()
    n, found = _name_at(words, 0, cast)
    if not n:
        return None, _NO_LABEL
    if len(found) != 1:
        return None, _SHARED
    rest = words[n:]
    if rest[:1] == ['s'] or _name_at(rest, 0, cast)[0] or (
            rest[:1] in (['and'], ['or']) and _name_at(rest, 1, cast)[0]):
        return None, _UNCLEAR
    for i in range(len(rest)):
        m = _name_at(rest, i, cast)[0] or (1 if rest[i] in _PRONOUNS else 0)
        if m and rest[i + m:i + m + 1] and rest[i + m] in _LABEL_SPEECH:
            return None, _UNCLEAR
    return next(iter(found)), ''


def _clauses(text: str) -> list[str]:
    """`text` cut where a clause ends: a full, question or exclamation
    stop followed (past any closing brackets or quote marks) by a space,
    a dash or the end (`(Pause. Rook shifts.) Maren`), but not one after
    a title (`brief_names._ABBREVIATIONS`, any case: `Sgt. Croy`); an
    ellipsis; | / ; or a line break."""
    from storyforge.brief_names import _ABBREVIATIONS
    out, start = [], 0
    for m in re.finditer(r'\.\.\.|…|[.!?]+[)\]"”’\'*_]*(?=\s|$|—|–)|[|/;\n]', text):
        if m.group().startswith('.') and not m.group().startswith('..'):
            word = re.search(r'(\w+)$', text[:m.start()])
            if word and word.group(1).lower() in _ABBREVIATIONS:
                continue
        out.append(text[start:m.start()])
        start = m.end()
    out.append(text[start:])
    return out


_DASH = r'(?:—|–|--?)'


def _label_speaker(before: str, after: str, cast: Cast) -> tuple[str | None, str]:
    """The character a brief gives a quoted span to, from the text around
    it in its item, and why not (`Scripted.why`) when there is none:
    either the last clause (`_clauses`) of the text before it, when that
    ends in a colon (`Dorren privately: "..."`, `(Pause. Rook shifts.)
    Maren: "..."`), or the first clause of the text after it, when that
    starts with a dash and doesn't end in a colon, which would make it the
    next line's label (`"..." — Lena`). The label must name one character
    with confidence (`_named`); a label holding a spaced dash (`Talia,
    afraid — and he hears himself:`) doesn't, nor does one that starts with
    anything but a name (`Council:`, `Spoken to the grave:`; `Cora hears:`
    still names Cora). Two labels that disagree name no one; one that
    names no one doesn't count against one that does (`Council: "..." —
    Thomas` is Thomas's). A wrong speaker here would send the brief's own
    words to the fix (the mended-bridle failure), so whatever is in doubt
    has no speaker, and is matched as before. Backslashes (escaped quotes
    in some briefs) are ignored."""
    if not cast.ids:
        return None, _NO_CAST
    labels = []
    before = before.replace('\\', '').strip()
    if before.endswith(':'):
        labels.append(re.sub(rf'^\s*{_DASH}\s*', '', _clauses(before[:-1])[-1]))
    after = _clauses(after.replace('\\', ''))[0]
    dash = re.match(rf'\s*{_DASH}\s*(.*)', after, re.S)
    if dash and not after.strip().endswith(':'):
        labels.append(dash.group(1))
    if not labels:
        return None, _NO_LABEL
    read = [(None, _UNCLEAR) if re.search(rf'\s{_DASH}\s', label) else _named(label, cast)
            for label in labels]
    named = {who for who, _ in read if who}
    if len(named) == 1:
        return named.pop(), ''
    if named:
        return None, _UNCLEAR
    return None, next((why for _, why in read if why != _NO_LABEL), _NO_LABEL)


def _brief_lines(project_dir: str, scene_id: str, cast: Cast | None = None) -> list[Scripted]:
    """The words the scene's brief scripts (`checker.PROMISE_FIELDS`), as
    phrases: each quoted span of an item, with the speaker the brief gives
    it (`_label_speaker`; `cast`: the characters, read when not given), and
    a `key_dialogue` item that quotes nothing, whole and with no speaker
    (a `Name:` label on it is part of the phrase, not read: quote the line
    to label it). An unquoted action or outcome is a paraphrase, not words
    the prose must use, so it isn't one. Phrases under `_MIN_BRIEF_WORDS`
    words are left out. A scene with no brief row scripts nothing."""
    from storyforge.checker import PROMISE_FIELDS, _split_cell
    from storyforge.elaborate import get_scene
    scene = get_scene(scene_id, os.path.join(project_dir, 'reference')) or {}
    lines: list[Scripted] = []
    for col in PROMISE_FIELDS:
        for item in _split_cell(scene.get(col) or ''):
            spans = list(re.finditer(r'"([^"]+)"|“([^”]+)”', item))
            if not spans:
                if col == 'key_dialogue':
                    lines.append(Scripted(item, None, _NO_QUOTES))
                continue
            if cast is None:
                cast = _cast(project_dir)
            for i, m in enumerate(spans):
                before = item[spans[i - 1].end() if i else 0:m.start()]
                after = item[m.end():spans[i + 1].start() if i + 1 < len(spans) else len(item)]
                who, why = _label_speaker(before, after, cast)
                lines.append(Scripted(m.group(1) or m.group(2), who, why))
    return [p for p in lines if _count(_words(p.text)) >= _MIN_BRIEF_WORDS]


def _brief_phrases(project_dir: str, scene_id: str) -> list[str]:
    """The words the scene's brief scripts (`_brief_lines`), without their
    speakers."""
    return [p.text for p in _brief_lines(project_dir, scene_id)]


#: A speech tag that may split a scripted line (`_is_speech_tag`): one of
#: these verbs with a pronoun or a character's name, nothing else
_SPEECH_VERBS = frozenset('said says asked asks answered replied told called whispered '
                          'murmured muttered shouted added repeated'.split())
#: Speech verbs whose object is the listener: only after the speaker
#: ("Thomas told", never "told Thomas")
_LISTENER_VERBS = frozenset({'told'})
_PRONOUNS = frozenset('he she they i we you'.split())
#: The most words a character's name in a speech tag may have
_MAX_NAME_WORDS = 3
#: Quote marks a scripted line is spoken between: double quotes, straight or
#: curly, and curly single quotes (a closing ’ followed by a letter is an
#: apostrophe, not a mark)
_QUOTE_MARKS = re.compile(r'["“”‘]|’(?!\w)')


def _tag_speaker(text: str, names: frozenset[str] | set[str]) -> str | None:
    """Who `text` names when it is only a speech tag: a speech verb
    (`_SPEECH_VERBS`) and a pronoun or a character's name (`names`, up to
    `_MAX_NAME_WORDS` words), either order, punctuation aside ("he said",
    "said Thomas"; "told" only after its speaker, `_LISTENER_VERBS`), as
    `_words` without the padding ("he", "thomas"). None when it isn't one:
    an adverb, a place or anything else in it makes it narration, which may
    hold the error."""
    words = _words(text).split()
    if not 2 <= len(words) <= _MAX_NAME_WORDS + 1:
        return None
    for verb, who, first in ((words[0], words[1:], True), (words[-1], words[:-1], False)):
        if first and verb in _LISTENER_VERBS:
            continue
        if verb in _SPEECH_VERBS and (
                (len(who) == 1 and who[0] in _PRONOUNS) or ' '.join(who) in names):
            return ' '.join(who)
    return None


def _is_speech_tag(text: str, names: frozenset[str] | set[str]) -> bool:
    """Whether `text` is only a speech tag (`_tag_speaker`)."""
    return _tag_speaker(text, names) is not None


def _split_parts(quote: str,
                 names: frozenset[str] | set[str] = frozenset()) -> tuple[str, list[str]] | None:
    """`quote` as one line the prose split with speech tags (`"Left hand on
    the case," he said. "Right hand free."`): its spoken words, and who each
    tag between them names (`_tag_speaker`). There must be two or more
    spoken parts, each tag between them only a speech tag, and no words
    before the first part or after the last. Otherwise None: narration
    before or after a line, or a tag with anything else in it, may be where
    the error is. Both readings of its quote marks are tried (a quote can
    start mid-line, so its first mark may close a line)."""
    segments = _QUOTE_MARKS.split(quote.replace('\r\n', '\n'))
    for parity in (0, 1):
        spoken = [x for i, x in enumerate(segments) if i % 2 == parity]
        told = [(i, x) for i, x in enumerate(segments) if i % 2 != parity]
        tags = [x for i, x in told if 0 < i < len(segments) - 1]
        ends = [x for i, x in told if not 0 < i < len(segments) - 1]
        who = [_tag_speaker(x, names) for x in tags]
        if (tags and sum(1 for x in spoken if _words(x).strip()) >= 2
                and None not in who
                and not any(_words(x).strip() for x in ends)):
            return ' '.join(spoken), who
    return None


def _split_line(quote: str, names: frozenset[str] | set[str] = frozenset()) -> str | None:
    """The spoken words of `quote` when it is one line the prose split with
    speech tags (`_split_parts`), else None."""
    parts = _split_parts(quote, names)
    return parts[0] if parts else None


#: The pronouns a speech tag is checked against the speaker's
#: (characters.csv `pronouns`): "I", "we" and "you" depend on who narrates
_CHECKED_PRONOUNS = frozenset({'he', 'she', 'they'})


def _tag_fits(who: str, speaker: str | None, cast: Cast) -> bool:
    """Whether a speech tag naming `who` (`_tag_speaker`) can be the brief's
    `speaker`. A name or alias fits when one of the characters it names is
    the speaker (a shared name fits each of them). "he", "she" or "they"
    fits unless the speaker's pronouns are known (`Cast.pronouns`) and are
    another. Anything that can't be told fits: no speaker in the brief,
    "I", "we", "you", or a speaker with no pronouns known."""
    if speaker is None:
        return True
    if who in _PRONOUNS:
        known = cast.pronouns.get(speaker)
        return who not in _CHECKED_PRONOUNS or not known or who == known
    return speaker in cast.ids.get(who, frozenset())


def _speaker_note(line: Scripted, tags: list[str], cast: Cast) -> str:
    """Whether the speaker of a split line matched to `line` was checked,
    for the report: `speaker checked: <name>` when every tag (`tags`) was
    told against the brief's speaker, else `speaker not checked: <why>`."""
    if line.speaker is None:
        return f'speaker not checked: {line.why}'
    name = cast.display.get(line.speaker, line.speaker)
    for who in tags:
        if who in _PRONOUNS and who not in _CHECKED_PRONOUNS:
            return f'speaker not checked: the tag says "{who}"'
        if who in _PRONOUNS and line.speaker not in cast.pronouns:
            return f'speaker not checked: {name}\'s pronouns are not known'
    return f'speaker checked: {name}'


def _plan_conflict(quote: str, phrases: list[str | Scripted], cast: Cast) -> str | None:
    """`_is_plan_conflict`'s verdict with the reason for the report: None
    when the quote isn't the brief's words, else whether the speaker was
    checked (`_speaker_note`; a quote no tag splits has none to check). Of
    several phrases that match, the note is the first one's that wasn't
    checked: the conflict was set aside without the check."""
    lines = [p if isinstance(p, Scripted) else Scripted(p) for p in phrases]
    split = _split_parts(quote, cast.names)
    if split is not None:
        lines = [p for p in lines if all(_tag_fits(w, p.speaker, cast) for w in split[1])]

    def hits(text: str, within: bool = False) -> list[Scripted]:
        q = _words(text)
        n = _count(q)
        if n < _MIN_BRIEF_WORDS:
            return []
        return [x for x in lines
                if q in _words(x.text) or (not within and _words(x.text) in q
                                           and 2 * _count(_words(x.text)) >= n)]
    found = hits(quote)
    # a split line's spoken words must all be the brief's: with the tag set
    # aside, nothing else in the quote may be (the error could be there)
    if split is not None:
        found += [x for x in hits(split[0], within=True) if x not in found]
    if not found:
        return None
    if split is None:
        return 'speaker not checked: no speech tag splits the quote'
    notes = [_speaker_note(x, split[1], cast) for x in found]
    return next((n for n in notes if n.startswith('speaker not')), notes[0])


def _is_plan_conflict(quote: str, phrases: list[str | Scripted], cast: Cast) -> bool:
    """Whether a contradiction's `quote` is the brief's own words: the
    quote lies within a scripted phrase, or a scripted phrase makes up at
    least half of it (a short scripted line inside a long quote whose error
    is elsewhere is not one). A quote under `_MIN_BRIEF_WORDS` words is
    never one.

    A scripted line the prose split with a speech tag (`"Left hand on the
    case," he said. "Right hand free."`) is matched on its spoken words
    (`_split_parts`; `cast`: the characters a tag may name): the
    mended-bridle run (2026-11-03) sent such a line, the brief's own, to
    the fix as a contradiction with a later scene, and the fix rewrote the
    scene to match that scene's error. Narration before or after a line is
    not taken out (`"...," said the dead man.`), and a tag with anything
    but a speaker and a speech verb is narration: either may hold the
    error. So is a tag naming someone not in characters.csv: the line isn't
    split, and isn't set aside. A split line's spoken words must all lie
    within one scripted phrase.

    The speaker each tag of a split line names must fit the one the brief
    gives the phrase (`Scripted.speaker`, `_tag_fits`): "Emmett said" on
    a line the brief gives Thomas is not the brief's words, and goes to the
    fix (#504's known limit). So is "she said" when Thomas's pronouns are
    known to be he. Not checked, so matched as before: a phrase the brief
    gives no one (a plain string, or `Scripted` with no speaker), "I",
    "we" or "you", a pronoun tag when the speaker's pronouns aren't known,
    and a tag after a line that isn't split (`"...," she said`, matched
    only by the half rule). The report says which (`_plan_conflict`)."""
    return _plan_conflict(quote, phrases, cast) is not None


# ============================================================================
# The book before a pass: what an error already there is (Ben, 2026-11-01)
# ============================================================================

@dataclass
class Snapshot:
    """The book before a pass (`snapshot`): the baseline against which the
    gate tells an error the pass made from one already there (`inherited`)."""
    #: scene id → prose, for the scenes whose prose is a baseline: readable,
    #: and not waiting on the gate
    scenes: dict[str, str] = field(default_factory=dict)
    #: reference file name → sha1 of its bytes (None: two files share the name)
    files: dict[str, str | None] = field(default_factory=dict)
    #: scene id → why it isn't in `scenes`
    left_out: dict[str, str] = field(default_factory=dict)


def _sha1(path: str) -> str | None:
    import hashlib
    try:
        with open(path, 'rb') as f:
            return hashlib.sha1(f.read()).hexdigest()
    except OSError:
        return None


def snapshot(project_dir: str) -> Snapshot:
    """The book as it is now, taken before a command writes prose and
    passed to the gate as `before=`. Take it once per run: a scene the run
    rewrites before another is gated then counts as changed.

    A scene listed in working/gate-pending.csv is left out (#480's review):
    its prose didn't pass the gate or wasn't checked, so a retry that keeps
    its error must not pass it as inherited. With the list unreadable every
    scene is left out. A scene that isn't UTF-8 is left out too."""
    snap = Snapshot()
    try:
        waiting = pending(project_dir)
    except GateError as e:
        waiting, unreadable = None, str(e)
    scenes_dir = os.path.join(project_dir, 'scenes')
    names = sorted(os.listdir(scenes_dir)) if os.path.isdir(scenes_dir) else []
    for name in names:
        if not name.endswith('.md'):
            continue
        sid = name[:-3]
        if waiting is None:
            snap.left_out[sid] = f'the pending list is unreadable: {unreadable}'
            continue
        if sid in waiting:
            snap.left_out[sid] = f'waiting on the gate ({waiting[sid]["command"]})'
            continue
        try:
            with open(os.path.join(scenes_dir, name), encoding='utf-8') as f:
                snap.scenes[sid] = f.read()
        except (OSError, UnicodeDecodeError) as e:
            snap.left_out[sid] = f'unreadable ({type(e).__name__})'
    ref_dir = os.path.join(project_dir, 'reference')
    for root, _, files in os.walk(ref_dir):
        for name in files:
            digest = _sha1(os.path.join(root, name))
            snap.files[name] = None if name in snap.files else digest
    return snap


def _unchanged_since(project_dir: str, snap: Snapshot, source: str, scene_id: str,
                     established_quote: str) -> bool:
    """Whether the established side of a contradiction is as it was in
    `snap` (#480's review: a contradiction is new when either side changed).
    A scene other than this one: its file is unchanged. This scene: the
    established quote was in it. A reference file or the calendar: its
    bytes are unchanged. The ledger, or anything unknown: no."""
    source = (source or '').strip()
    if not source:
        return False
    if source == scene_id:
        return _quoted_in(established_quote, snap.scenes.get(scene_id, ''))
    if source in snap.scenes:
        try:
            with open(os.path.join(project_dir, 'scenes', f'{source}.md'),
                      encoding='utf-8') as f:
                return f.read() == snap.scenes[source]
        except (OSError, UnicodeDecodeError):
            return False
    old = snap.files.get(source)
    if old is None:
        return False
    found = [os.path.join(root, source) for root, _, files
             in os.walk(os.path.join(project_dir, 'reference')) if source in files]
    return len(found) == 1 and _sha1(found[0]) == old


def _classify(result: GateResult, project_dir: str, before: Snapshot | None,
              reported: list[dict[str, str]]) -> None:
    """Sort the check's verified contradictions into `inherited` and
    `plan_conflicts` (each set anew).

    Inherited: the error was in the book before this pass. Either its
    words (`_quoted_in`) were in the scene in `before` and its established
    side is unchanged since (`_unchanged_since`), or the author was already
    told of it (`reported`: the same source and quote, from
    working/gate-reported.csv). Inherited comes first: an error the pass
    didn't make doesn't stop it, whatever its source.

    Plan conflict: its words are the brief's own (`_is_plan_conflict`;
    a split line's speech tags must fit the speaker the brief names).

    Broken promises and unverified findings are neither."""
    result.inherited, result.plan_conflicts, result.speaker_notes = [], [], []
    if not result.check:
        return
    old = before.scenes.get(result.scene_id) if before else None
    known = {(r['source'], _words(r['quote'])) for r in reported}
    phrases = None
    for f in result.check.findings:
        if f.kind != 'contradiction' or not f.scene_quote.strip():
            continue
        if ((f.established_scene or '', _words(f.scene_quote)) in known
                or (old is not None and _quoted_in(f.scene_quote, old)
                    and _unchanged_since(project_dir, before, f.established_scene,
                                         result.scene_id, f.established_quote))):
            result.inherited.append(f)
            continue
        if phrases is None:
            cast = _cast(project_dir)
            _warn_once(cast.warnings)
            phrases = _brief_lines(project_dir, result.scene_id, cast)
        note = _plan_conflict(f.scene_quote, phrases, cast)
        if note is not None:
            result.plan_conflicts.append(f)
            result.speaker_notes.append((f, note))


def _hold_back(result: GateResult, also: list[Finding] | None = None,
               prose: str = '', rows: list[dict[str, str]] | None = None) -> None:
    """Take out of `proposed` each commitment stating an inherited
    contradiction (its quote and the finding's overlap), so the ledger never
    records a fact the check showed contradicts the book (#480's review).
    `also`: more findings to hold back for (a provisional commit's, #556),
    matched wider, since the checker's quote and the fact's need not share
    words ("he seized thirty sleepers" against a fact quoting "thirty of the
    thanes"): a commitment is held back for one when its quote overlaps the
    finding's, lies in the same paragraph of `prose` as the finding's quote,
    or has the subject and type of the fact the finding says it
    contradicts (`_finding_subjects` over `rows`, the ledger). They go to `held_back`,
    reported."""
    def overlaps(quote: str, f: Finding) -> bool:
        return bool(f.scene_quote) and _count(quote) >= _MIN_BRIEF_WORDS and (
            quote in _words(f.scene_quote) or _words(f.scene_quote) in quote)

    paras = [p for p in re.split(r'\n\s*\n', prose) if p.strip()] if prose else []

    def paragraph(quote: str) -> set[int]:
        return {i for i, p in enumerate(paras) if quote and _found_in(quote, p)}

    def subject(row: dict[str, str]) -> str:
        return (row.get('subject') or '').strip().casefold()

    wide = []
    for f in also or []:
        at = paragraph(f.scene_quote)
        # the finding's claim: its values, about the subjects of the facts
        # stating it (a quote overlapping it, or in its paragraph)
        stating = {subject(r) for r in result.proposed
                   if overlaps(_words(r.get('quote') or ''), f)
                   or (paragraph(r.get('quote') or '') & at)} - {''}
        wide.append((f, at, _finding_subjects(f, rows or []), _values(f.scene_quote), stating))
    keep = []
    # a source-backed contradiction whose earlier fact couldn't be found to
    # supersede is held back like an inherited one (`_source_supersede`)
    strict = result.inherited + list(result.source_unmatched)
    for row in result.proposed:
        quote = _words(row.get('quote') or '')
        hit = next((f for f in strict if overlaps(quote, f)), None)
        if hit is None and wide:
            where = paragraph(row.get('quote') or '')
            key = (subject(row), row.get('type') or '')
            values = _values(f"{row.get('statement', '')} {row.get('quote', '')}")
            hit = next((f for f, at, subjects, claim, stating in wide
                        if overlaps(quote, f) or (where & at)
                        or (key[0] and key in subjects)
                        # #556's review: the claim restated elsewhere ("412
                        # residents" three paragraphs on)
                        or (values & claim and (not stating or key[0] in stating))),
                       None)
        if hit is None:
            keep.append(row)
        else:
            result.held_back.append((row.get('statement', ''), hit))
    result.proposed = keep


_UNITS = {w: n for n, w in enumerate(
    'zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen '
    'fifteen sixteen seventeen eighteen nineteen'.split())}
_TENS = {w: 10 * n for n, w in enumerate(
    'twenty thirty forty fifty sixty seventy eighty ninety'.split(), start=2)}
_SCALES = {'hundred': 100, 'thousand': 1000, 'million': 1_000_000}


def _values(text: str) -> set[int]:
    """The numbers `text` states, in digits or words ("four hundred and
    twelve" and "412" are both 412), for matching a claim restated in other
    words."""
    out: set[int] = set()
    total = current = 0
    seen = False
    for w in re.findall(r"[a-z]+|\d[\d,]*", text.lower()):
        if w[0].isdigit():
            out.add(int(w.replace(',', '')))
            continue
        if w in _UNITS:
            current += _UNITS[w]
        elif w in _TENS:
            current += _TENS[w]
        elif w in _SCALES:
            if _SCALES[w] == 100:
                current = max(current, 1) * 100
            else:
                total += max(current, 1) * _SCALES[w]
                current = 0
        elif w == 'and' and seen:
            continue
        else:
            if seen:
                out.add(total + current)
            total = current = 0
            seen = False
            continue
        seen = True
    if seen:
        out.add(total + current)
    return out


def _finding_subjects(f: Finding, rows: list[dict[str, str]]) -> set[tuple[str, str]]:
    """The (subject casefolded, type) of the ledger facts `f` says the
    scene contradicts: the one its `fact_id` names, or the commitments of
    its established scene whose quote holds the established words (or is
    held by them)."""
    out = set()
    for r in rows:
        subject = (r.get('subject') or '').strip().casefold()
        if not subject:
            continue
        if f.fact_id and r.get('id') == f.fact_id:
            out.add((subject, r.get('type') or ''))
        elif (f.established_scene and (r.get('scene_id') or '').strip() == f.established_scene
              and f.established_quote and r.get('quote')
              and (_found_in(r['quote'], f.established_quote)
                   or _found_in(f.established_quote, r['quote']))):
            out.add((subject, r.get('type') or ''))
    return out


def _apply_source(result: GateResult, project_dir: str, scene_id: str, prose: str,
                  order: dict[str, int], log_dir: str, model: str,
                  old_rows: list[dict[str, str]] = ()) -> None:
    """The source check (`gate_source`, #557) for a faithful adaptation:
    drop the proposed facts the source contradicts (`source_dropped`) and
    take the verified contradictions with an earlier scene the source backs
    this scene on out of the findings (`source_backed`). Says in
    `source_notes` why it didn't run, or what it didn't rule on; a failed
    call is a note, never a stop.

    Cost (#557's review): only the proposed facts new to the scene (no
    earlier commitment of it states the same fact, `ledger.fact_key`) are
    sent, and with none of those and no contradiction to rule on there is
    no call (a re-check of an unchanged scene); a fix round whose facts and
    contradictions are what an earlier run of this process sent reuses its
    ruling (`gate_source.review`'s memo)."""
    from storyforge import gate_source
    ctx = gate_source.setup(project_dir)
    if ctx is None:
        return
    if ctx.skip:
        result.source_notes.append(f'not checked against the source: {ctx.skip}')
        return
    if scene_id not in ctx.refs:
        result.source_notes.append('not checked against the source: the scene is invented '
                                   'or not mapped in reference/source-map.csv')
        return
    at = order.get(scene_id, 0)
    contradictions = [f for f in result.findings
                      if f.kind == 'contradiction' and not _among(f, result.plan_conflicts)
                      and f.established_scene in order and order[f.established_scene] < at]
    known = {ledger.fact_key(r) for r in old_rows}
    fresh = [i for i, r in enumerate(result.proposed) if ledger.fact_key(r) not in known]
    if not fresh and not contradictions:
        return
    try:
        review = gate_source.review(project_dir, scene_id, prose,
                                    [result.proposed[i] for i in fresh],
                                    contradictions, model=model,
                                    log_file=gate_source.log_file(log_dir, scene_id), ctx=ctx)
    except gate_source.SourceReviewError as e:
        result.source_notes.append(f'not checked against the source: {e}')
        return
    result.source_notes.extend(review.notes)
    result.source_ruled = bool(fresh) and review.ruled >= set(range(len(fresh)))
    gone = {fresh[i] for i, _ in review.dropped}
    result.source_dropped = [(result.proposed[fresh[i]].get('statement', ''), why)
                             for i, why in review.dropped]
    result.proposed = [r for i, r in enumerate(result.proposed) if i not in gone]
    result.source_backed = [(contradictions[i], why) for i, why in review.backs_scene]


def has_commitments(project_dir: str, scene_id: str) -> bool:
    """Whether the ledger holds commitments from `scene_id`'s prose."""
    return any(ledger.is_commitment(r) and (r.get('scene_id') or '').strip() == scene_id
               for r in ledger.load(project_dir))


def gate_scene(project_dir: str, scene_id: str, *, command: str, prose: str | None = None,
               log_dir: str, extract_model: str | None = None,
               check_model: str | None = None,
               introduced_by: str | None = None,
               before: Snapshot | None = None) -> GateResult:
    """`_gate_scene`, with its model calls (extraction, the persistence check,
    every reading of the check) written to the cost ledger as `gate` rows for
    the scene, whether or not it finishes (F-151)."""
    from storyforge import api
    with api.metered() as meter:
        try:
            return _gate_scene(project_dir, scene_id, command=command, prose=prose,
                               log_dir=log_dir, extract_model=extract_model,
                               check_model=check_model, introduced_by=introduced_by,
                               before=before)
        finally:
            _log_spend(meter, project_dir, 'gate', scene_id)


def _log_spend(meter, project_dir: str, operation: str, scene_id: str) -> None:
    """Write a meter's spend to the cost ledger; a failed write is a warning,
    never an error that hides the gate's own."""
    from storyforge.common import log
    try:
        meter.log(project_dir, operation, scene_id)
    except Exception as e:
        log(f'WARNING: could not log the cost of {operation} {scene_id}: {e}')


def _gate_scene(project_dir: str, scene_id: str, *, command: str, prose: str | None = None,
                log_dir: str, extract_model: str | None = None,
                check_model: str | None = None,
                introduced_by: str | None = None,
                before: Snapshot | None = None) -> GateResult:
    """Extract, halt, check and (if all clear) commit `scene_id`'s prose:
    `prose`, or the scene file when None. `command` is the command that
    wrote the prose (one of `GATE_COMMANDS`), recorded as the new rows'
    `introduced_by` and as the audit log's command.

    A redraft is extracted and checked against the ledger without its
    earlier version's commitments, and the `resolves` that version set on
    earlier commitments are cleared (this version's `ends` set them again).
    A `resolves` it set on a registry state isn't touched: the gate never
    sets one there. `introduced_by` (default `command`) is what the new rows
    record; a re-check keeps the prose's writer.

    `before` is the book before the pass that wrote `prose` (`snapshot`;
    None: a new scene, a re-check, or advisor mode). A contradiction that
    was already there is `inherited`: reported, not blocking (Ben,
    2026-11-01: a pass doesn't stop on an error it didn't make), and so is
    one already in working/gate-reported.csv, whatever the command; the
    commitments stating one aren't recorded (`held_back`). On commit the
    scene's rows in that file are replaced by this run's inherited
    findings. A contradiction in the brief's own words is a
    `plan_conflict` (`_classify`).

    On commit (Phase 4, `docs/plans/2026-10-31-phase4-safe-revision-design.md`):
    a new commitment stating the same fact as an earlier one of the scene
    (`ledger.fact_key`) keeps its id, and a later scene's end of it, so
    links to it hold. The earlier commitments with no such match, and the
    earlier states whose end in this scene came or went, are `changed`;
    the later scenes whose facts depend on them (`ledger.dependents`) and
    have prose are listed in `working/gate-pending.csv` as `recheck`
    (`recheck_pending` re-gates them). A fact new to the scene doesn't list
    anything: its own check already reads it against the later scenes.

    Raises:
        GateError: a step couldn't finish (extraction or the check failed,
            the scene has no prose, or the ledger changed on disk
            while the gate ran); nothing was written.
        ValueError: `command` isn't one of `GATE_COMMANDS`.
    """
    from storyforge.common import select_model
    from storyforge.extract import COMMITMENT_PROBLEMS
    if command not in GATE_COMMANDS:
        raise ValueError(f'command must be one of {", ".join(GATE_COMMANDS)}, not {command!r}')
    if prose is None:
        path = os.path.join(project_dir, 'scenes', f'{scene_id}.md')
        try:
            with open(path, encoding='utf-8') as f:
                prose = f.read()
        except OSError as e:
            raise GateError(f'{scene_id}: no prose to gate ({e})') from e
    if not prose.strip():
        raise GateError(f'{scene_id}: no prose to gate (the scene is empty)')
    if prose.lstrip().startswith('---\n'):
        raise GateError(f'{scene_id}: the scene starts with frontmatter; scene files are '
                        f'pure prose (`storyforge cleanup` strips it)')
    try:
        rows = ledger.load(project_dir)
        order = ledger.scene_order(project_dir)
        # read before the model calls: a commit needs both
        names, name_notes = ledger.subject_names(project_dir)
        revised_rejection = rejected_ids(pending(project_dir).get(scene_id))
        already_reported = reported(project_dir).get(scene_id, [])
    except (ledger.LedgerError, ValueError, OSError, UnicodeDecodeError) as e:
        raise GateError(f'{scene_id}: {e}') from e
    loaded = copy.deepcopy(rows)
    if scene_id not in order:
        raise GateError(f'{scene_id} is not a scene in reference/scenes.csv')

    # The scene's earlier commitments (a redraft's) aren't offered back to it
    # and are replaced on commit; what leans on them is re-checked (Phase 4)
    # (binding ones: a rejected commitment stays, the record of the
    # author's decision, and prose restating it is a problem below)
    old_rows = [copy.deepcopy(r) for r in rows if ledger.is_commitment(r)
                and r.get('status') == 'binding'
                and (r.get('scene_id') or '').strip() == scene_id]
    rejected_here = {ledger.fact_key(r): r['id'] for r in rows
                     if r.get('status') == 'rejected'
                     and (r.get('scene_id') or '').strip() == scene_id}
    old = {r['id'] for r in old_rows}
    ended_before = ledger.ended_by(rows, scene_id)
    rows = [r for r in rows if r['id'] not in old]
    # ... and the ends the earlier version set: this version's extraction
    # sets its own
    for r in rows:
        if ledger.is_commitment(r) and (r.get('resolves') or '').strip() == scene_id:
            r['resolves'] = ''

    result = GateResult(scene_id, problems={k: [] for k in COMMITMENT_PROBLEMS + ('rejected',)})
    result.proposed = _extract(project_dir, scene_id, prose, rows, order,
                               introduced_by or command,
                               extract_model or select_model('evaluation'), log_dir,
                               result.problems, result.dropped)
    # A fact the author rejected may not come back as binding
    for r in result.proposed:
        rid = rejected_here.get(ledger.fact_key(r))
        if rid:
            result.problems['rejected'].append(
                f'{scene_id}: "{r.get("quote") or r.get("statement")}" restates {rid}, '
                f'which the author rejected')
        result.halts = audit.halting_conditions(result.proposed, rows)
    try:
        result.check = check_scene(project_dir, scene_id, prose=prose, model=check_model,
                                   log_file=os.path.join(log_dir, f'gate-check-{scene_id}.json'),
                                   rows=rows, disputes=_disputes(result, rows),
                                   readings=GATE_READINGS)
    except CheckError as e:
        error = GateError(str(e))
        error.run = getattr(e, 'run', None)
        raise error from e
    _classify(result, project_dir, before, already_reported)
    result._ctx = _CommitContext(rows, loaded, old_rows, ended_before, revised_rejection,
                                 names, name_notes, order, prose, command)
    _apply_source(result, project_dir, scene_id, prose, order, log_dir,
                  extract_model or select_model('evaluation'), old_rows)
    if not result.passed:
        _note_blocked(project_dir, scene_id, command, result)
        return result
    _commit(project_dir, result)
    return result


@dataclass
class _CommitContext:
    """What `_gate_scene` read before its model calls, for `_commit`."""
    rows: list[dict[str, str]]          # the ledger without the scene's old commitments
    loaded: list[dict[str, str]]        # the ledger as loaded
    old_rows: list[dict[str, str]]
    ended_before: set[str]
    revised_rejection: list[str]
    names: dict[str, set[str]]
    name_notes: list[str]
    order: dict[str, int]
    prose: str
    command: str


#: A pending row's command for a scene `write --keep-going` committed
#: without a pass (`commit_provisional`): its facts are in the ledger, less
#: those stating what stopped it, and its findings are the author's
PROVISIONAL = 'provisional'


def can_commit_provisionally(result: GateResult) -> str:
    """Why `result` can't be committed provisionally ('' when it can): only
    the check's findings stopped it (contradictions, broken promises, plan
    conflicts, unverified ones). A halt (a fixed fact changed), an
    extraction problem or an unruled dispute would commit a wrong row."""
    if result.passed or result.committed:
        return 'it was committed'
    if getattr(result, '_ctx', None) is None:
        return 'the gate run did not finish'
    if result.halts:
        return 'it changes a fixed fact (a halt)'
    if result.unresolved:
        return 'extraction left problems a commit would write'
    if result.unruled:
        return 'the check gave no ruling on a plan fact the scene may change'
    return ''


def commit_provisional(project_dir: str, result: GateResult, reason: str) -> None:
    """Commit a scene that didn't pass, for `write --keep-going` (#556,
    G-028/B-028/B-030: one stop ended an unattended draft): its commitments,
    less each one stating a blocking finding (`_hold_back`), replace its
    earlier ones as on a pass, and what they changed is listed for a
    re-check; the scene is listed `PROVISIONAL` in `PENDING_PATH` with
    `reason`, and its verified contradictions stay in `BLOCKED_PATH` for
    `storyforge check --accept`. A later scene is then drafted from
    everything the scene got right. Sets `.committed` and `.provisional`.

    Raises:
        GateError: `can_commit_provisionally` says no, or the ledger changed
            since the gate run (nothing written).
    """
    why = can_commit_provisionally(result)
    if why:
        raise GateError(f'{result.scene_id}: not committed provisionally: {why}')
    _commit(project_dir, result, holding=result.findings + result.unverified,
            pending_reason=reason)
    result.provisional = True


def _commit(project_dir: str, result: GateResult, holding: list[Finding] | None = None,
            pending_reason: str = '') -> None:
    """Write `result`'s commitments (its gate run's `_ctx`): on a pass, or
    provisionally (`holding`: the findings it was committed in spite of,
    whose commitments are held back, and `pending_reason` for its
    `PROVISIONAL` row)."""
    ctx = result._ctx
    scene_id, command, prose = result.scene_id, ctx.command, ctx.prose
    rows, old_rows, order = ctx.rows, ctx.old_rows, ctx.order
    ended_before, revised_rejection = ctx.ended_before, ctx.revised_rejection
    names, name_notes = ctx.names, ctx.name_notes
    # The model calls take minutes: a ledger changed meanwhile would be
    # overwritten, and its change logged under this command
    try:
        if ledger.load(project_dir) != ctx.loaded:
            raise GateError(f'{scene_id}: reference/commitments.csv changed while the '
                            f'scene was being gated; nothing written, gate it again')
    except ledger.LedgerError as e:
        raise GateError(f'{scene_id}: {e}') from e
    _source_supersede(result, rows)
    fixed_toward_source = _keep_superseded(project_dir, result, rows, prose)
    # #558's second review: the kept facts go through the hold-back too
    _keep_steady(project_dir, result, old_rows, prose)
    _hold_back(result, holding, prose=prose if holding else '', rows=rows)
    _carry_ids(result.proposed, old_rows, rows, scene_id)
    new = rows + result.proposed
    for rid, quote in result.check.kept:
        if ledger.fill_quote(new, rid, quote):
            result.quotes_filled.append(rid)
    # the old side only: a fact new to the scene lists nothing
    new_keys = {ledger._fact_key(r) for r in result.proposed}
    result.changed = [r['id'] for r in old_rows if ledger._fact_key(r) not in new_keys]
    result.changed += sorted(ended_before ^ ledger.ended_by(new, scene_id))
    result.changed += [i for i in revised_rejection if i not in result.changed]
    if result.changed:
        found = ledger.dependents(old_rows + new, result.changed, order, names=names)
        result.unrelated = found.unrelated
        result.name_notes = name_notes
        # a rejected fact's re-check also reaches the scenes whose brief
        # names it, as `audit --mark rejected` tells the author it will
        briefs = audit.leaning_scenes(project_dir, revised_rejection) if revised_rejection else {}
        named = {b for v in briefs.values() for b in v}
        # only what follows the scene can depend on how the scene changed
        later = sorted({s for s in set(found.scenes) | named
                        if s in order and order[s] > order[scene_id]}, key=order.get)
        gone = _gone_scenes(project_dir)
        result.recheck = [s for s in later if s not in gone and _has_prose(project_dir, s)]
        result.not_rechecked = [f'{s} ({"cut or merged" if s in gone else "no prose yet"})'
                                for s in later if s not in result.recheck]
        result.not_rechecked += [f'{s} (its brief names a rejected fact, but it is not in '
                                 f'scenes.csv)' for s in sorted(named - set(order))]
        removed = set(result.changed) - {r['id'] for r in result.proposed}
        result.dangling = [f'{r["id"]} → {ref}' for r in rows if not ledger.is_commitment(r)
                           for col in ('supersedes', 'depends_on')
                           for ref in ledger._split(r.get(col, '')) if ref in removed]
    ledger.save(project_dir, new, command=command)
    result.committed = True
    note = record_prose(project_dir, scene_id, prose)
    if note:
        result.prose_notes.append(f'{scene_id}: {note}')
    if fixed_toward_source:
        try:
            clear_source_fix(project_dir, scene_id)
        except GateError as e:
            result.source_notes.append(f'{SOURCE_FIX_PATH} could not be updated ({e}); '
                                       f'remove {scene_id}\'s row by hand')
    try:
        record_reported(project_dir, scene_id, command, result.inherited, prose=prose)
        if holding is None:
            record_blocked(project_dir, scene_id, command, [])
    except GateError as e:   # the ledger is written; the findings were logged
        from storyforge.common import log
        log(f'WARNING: {scene_id} passed, but {REPORTED_PATH} could not be updated: {e}. '
            f'Its contradictions already in the scene are only in this log.')
    try:
        if holding is not None:
            mark_pending(project_dir, scene_id, PROVISIONAL, pending_reason)
        else:
            clear_pending(project_dir, scene_id)
        waiting = pending(project_dir)
        for sid in result.recheck:
            if sid not in waiting:   # one waiting for another reason stays as it is
                mark_pending(project_dir, sid, RECHECK,
                             f're-check: {scene_id} changed {len(result.changed)} fact(s) '
                             f'its facts depend on')
        for f, why in result.source_backed:
            mark_source_fix(project_dir, f.established_scene,
                            f'{scene_id} tells it the source\'s way and this scene does not: '
                            f'"{_one_line(f.established_quote)[:120]}" ({_one_line(why)[:160]})')
        if result.source_dropped:
            mark_source_fix(project_dir, scene_id,
                            f'the source contradicts {len(result.source_dropped)} fact(s) read '
                            f'from it, not recorded: '
                            + '; '.join(_one_line(st)[:100] for st, _ in result.source_dropped[:3]),
                            prose=prose)
    except GateError as e:   # the ledger is written; say why the list wasn't updated
        from storyforge.common import log
        log(f'WARNING: {scene_id} passed, but {PENDING_PATH} could not be updated: {e}. '
            f'Fix it by hand: remove {scene_id}\'s row'
            + (f' and add {", ".join(result.recheck)} for a re-check' if result.recheck else '')
            + '.')


def _finding_fact_ids(f: Finding, rows: list[dict[str, str]]) -> list[str]:
    """The binding commitments `f` says the scene contradicts: the one its
    `fact_id` names, or those of its established scene whose quote holds
    the established words (or is held by them)."""
    out = []
    for r in rows:
        if not ledger.is_commitment(r) or r.get('status') != 'binding':
            continue
        if f.fact_id and r.get('id') == f.fact_id:
            out.append(r['id'])
        elif (f.established_scene and (r.get('scene_id') or '').strip() == f.established_scene
              and f.established_quote and r.get('quote')
              and (_found_in(r['quote'], f.established_quote)
                   or _found_in(f.established_quote, r['quote']))):
            out.append(r['id'])
    return out


def _source_supersede(result: GateResult, rows: list[dict[str, str]]) -> None:
    """For each contradiction the source backs this scene on (#557's
    review): the earlier scene's commitments stating it become
    `superseded` (no longer binding), so later scenes are drafted and
    checked against the source's telling, which this scene's facts then
    commit. One whose earlier fact can't be found is held back instead
    (`source_unmatched`, `_hold_back`). In place on `rows`."""
    result.source_superseded, result.source_unmatched = [], []
    for f, _ in result.source_backed:
        ids = _finding_fact_ids(f, rows)
        if not ids:
            result.source_unmatched.append(f)
            continue
        for r in rows:
            if r.get('id') in ids:
                r['status'] = 'superseded'
        result.source_superseded += [i for i in ids if i not in result.source_superseded]


#: The scenes listed for the author to fix toward the source (#557), apart
#: from working/gate-pending.csv so a re-check's pass there never clears
#: one (#557's second review): `scene_id|prose|reason`, `prose` the sha1 of
#: the scene's prose when listed. Only a commit of that scene with other
#: prose takes a row off (`_keep_superseded`, `clear_source_fix`)
SOURCE_FIX_PATH = 'working/gate-source-fix.csv'
_SOURCE_FIX_COLUMNS = ['scene_id', 'prose', 'reason']


def _prose_sha(text: str) -> str:
    import hashlib
    return hashlib.sha1(text.encode('utf-8')).hexdigest()


def _scene_sha(project_dir: str, scene_id: str) -> str:
    try:
        with open(os.path.join(project_dir, 'scenes', f'{scene_id}.md'), encoding='utf-8') as f:
            return _prose_sha(f.read())
    except (OSError, UnicodeDecodeError):
        return 'none'


def source_fixes(project_dir: str) -> dict[str, dict[str, str]]:
    """Scene id → its `SOURCE_FIX_PATH` row.

    Raises:
        GateError: the file is malformed or unreadable."""
    path = os.path.join(project_dir, SOURCE_FIX_PATH)
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding='utf-8') as f:
            lines = [line.rstrip('\n') for line in f if line.strip()]
    except (OSError, UnicodeDecodeError) as e:
        raise GateError(f'{SOURCE_FIX_PATH}: {e}') from e
    if not lines or lines[0].split('|') != _SOURCE_FIX_COLUMNS:
        raise GateError(f'{SOURCE_FIX_PATH}: the header must be {"|".join(_SOURCE_FIX_COLUMNS)}')
    out = {}
    for line in lines[1:]:
        cells = line.split('|', 2)
        if len(cells) != 3:
            raise GateError(f'{SOURCE_FIX_PATH}: a bad row: {line[:80]!r}')
        out[cells[0]] = dict(zip(_SOURCE_FIX_COLUMNS, cells))
    return out


def _write_source_fixes(project_dir: str, rows: dict[str, dict[str, str]]) -> None:
    path = os.path.join(project_dir, SOURCE_FIX_PATH)
    if not rows:
        if os.path.isfile(path):
            os.remove(path)
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='') as f:
        f.write('|'.join(_SOURCE_FIX_COLUMNS) + '\n')
        for sid in sorted(rows):
            f.write('|'.join(rows[sid][c] for c in _SOURCE_FIX_COLUMNS) + '\n')


def mark_source_fix(project_dir: str, scene_id: str, why: str, prose: str | None = None) -> None:
    """List `scene_id` for the author to fix toward the source (#557), in
    `SOURCE_FIX_PATH`, with the prose it has now (`prose`, else the scene
    file): the row stays until a commit of the scene with other prose. A
    scene listed already gets `why` added."""
    from storyforge.common import csv_safe
    rows = source_fixes(project_dir)
    sha = _prose_sha(prose) if prose is not None else _scene_sha(project_dir, scene_id)
    why = csv_safe(_one_line(why))
    old = rows.get(scene_id)
    if old and why in old['reason']:
        return
    reason = f"{old['reason']} / {why}" if old else why
    rows[scene_id] = {'scene_id': scene_id, 'prose': sha, 'reason': reason}
    _write_source_fixes(project_dir, rows)


def clear_source_fix(project_dir: str, scene_id: str) -> None:
    rows = source_fixes(project_dir)
    if rows.pop(scene_id, None) is not None:
        _write_source_fixes(project_dir, rows)


def source_fix_waits(project_dir: str, scene_id: str, prose: str | None = None) -> bool:
    """Whether `scene_id` is listed to fix toward the source and its prose
    (`prose`, else the scene file) hasn't changed since: checking it again
    can't clear the row."""
    try:
        row = source_fixes(project_dir).get(scene_id)
    except GateError:
        return False
    if not row:
        return False
    sha = _prose_sha(prose) if prose is not None else _scene_sha(project_dir, scene_id)
    return row['prose'] == sha


def _keep_superseded(project_dir: str, result: GateResult, rows: list[dict[str, str]],
                     prose: str) -> bool:
    """#557's second and third reviews: a scene's `superseded` commitments
    (the source ruled them wrong) are never bound again. A proposed row
    restating one is dropped: the same fact, a quote holding or held by its
    quote, or the same subject and a value it states (`_values`: "300
    people" from another sentence, filed under another type). One is
    retired (taken out of `rows`) only when the scene is listed to fix
    toward the source and its prose was fixed: the words its quote came
    from are gone from the prose, nothing proposed restates it, and the
    source check ruled on every new fact (a failed call, or one that gave
    no verdict, retires nothing: a one-word edit elsewhere or an added
    newline isn't a fix). Returns True when every one was retired, so the
    listing comes off after the commit."""
    mine = [r for r in rows if r.get('status') == 'superseded'
            and (r.get('scene_id') or '').strip() == result.scene_id
            and ledger.is_commitment(r)]
    try:
        listed = source_fixes(project_dir).get(result.scene_id)
    except GateError as e:
        result.source_notes.append(str(e))
        listed = None
    if not mine:
        return bool(listed) and listed['prose'] != _prose_sha(prose) and result.source_ruled

    def subject(r: dict[str, str]) -> str:
        return (r.get('subject') or '').strip().casefold()

    def restates(p: dict[str, str], r: dict[str, str]) -> bool:
        q, o = _words(p.get('quote') or ''), _words(r.get('quote') or '')
        if ledger.fact_key(p) == ledger.fact_key(r):
            return True
        if _count(q) >= _MIN_QUOTE_WORDS and o.strip() and (q in o or o in q):
            return True
        values = _values(r.get('statement', ''))
        return bool(subject(r) and subject(p) == subject(r) and values
                    and values & _values(p.get('statement', '')))
    again = [p for p in result.proposed if any(restates(p, r) for r in mine)]
    if again:
        result.proposed = [p for p in result.proposed if p not in again]
        result.source_notes.append('not recorded, the source ruled them wrong (superseded): '
                                   + '; '.join(_one_line(p.get('statement', ''))[:100]
                                               for p in again))
    if not listed or listed['prose'] == _prose_sha(prose):
        return False
    if not result.source_ruled:
        result.source_notes.append('superseded rows kept and the source fix left open: the '
                                   'source check gave no ruling on this prose')
        return False
    fixed = [r for r in mine if not (r.get('quote') and _found_in(r['quote'], prose))
             and not any(restates(p, r) for p in again)]
    if fixed:
        gone = {r['id'] for r in fixed}
        rows[:] = [r for r in rows if r.get('id') not in gone]
        result.source_notes.append(f'retired, the prose fixed toward the source: '
                                   f'{", ".join(sorted(gone))}')
    return len(fixed) == len(mine)


#: The prose each committed scene's commitments were read from, as the git
#: blob of its text (#558): what `steady_facts` diffs a later version
#: against. Rows replaced on each commit
PROSE_PATH = 'working/gate-prose.csv'
_PROSE_COLUMNS = ['scene_id', 'blob']


def _git_out(project_dir: str, *args: str, data: bytes | None = None) -> bytes | None:
    import subprocess
    try:
        r = subprocess.run(['git', '-C', project_dir, *args], input=data,
                           capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


def _prose_rows(project_dir: str) -> dict[str, str]:
    path = os.path.join(project_dir, PROSE_PATH)
    if not os.path.isfile(path):
        return {}
    with open(path, encoding='utf-8') as f:
        lines = [line.rstrip('\n') for line in f if line.strip()]
    if not lines or lines[0].split('|') != _PROSE_COLUMNS:
        raise ValueError(f'{PROSE_PATH}: the header must be {"|".join(_PROSE_COLUMNS)}')
    return dict(line.split('|', 1) for line in lines[1:] if '|' in line)


def gated_prose(project_dir: str, scene_id: str) -> tuple[str | None, str]:
    """The prose `scene_id`'s commitments were last read from (`PROSE_PATH`,
    read back from git), or None and why not."""
    try:
        blob = _prose_rows(project_dir).get(scene_id)
    except (OSError, UnicodeDecodeError, ValueError) as e:
        return None, f'{PROSE_PATH} can\'t be read ({e})'
    if not blob:
        earlier = _prose_from_history(project_dir, scene_id)
        if earlier is not None:
            return earlier, ''
        return None, f'{PROSE_PATH} doesn\'t record the prose its facts were read from'
    out = _git_out(project_dir, 'cat-file', 'blob', blob)
    if out is None:
        return None, f'git has no blob {blob[:12]} (the prose its facts were read from)'
    return out.decode('utf-8', errors='replace'), ''


#: How far back `_prose_from_history` looks through the ledger's commits.
_HISTORY_DEPTH = 300


def _scene_rows(text: str, scene_id: str) -> list[str] | None:
    """The ledger lines of `scene_id` in a ledger's text, sorted; None when
    the text has no scene_id column."""
    lines = text.splitlines()
    if not lines or 'scene_id' not in lines[0].split('|'):
        return None
    at = lines[0].split('|').index('scene_id')
    return sorted(line for line in lines[1:]
                  if (cells := line.split('|')) and len(cells) > at and cells[at] == scene_id)


def _prose_from_history(project_dir: str, scene_id: str) -> str | None:
    """The prose `scene_id`'s commitments were read from, for a book gated
    before `PROSE_PATH` existed (Beowulf B-033): the scene file as it stood at
    the latest commit that changed the scene's ledger rows. The gate commits
    a scene's facts with the prose it read; revise's commit of the prose
    alone, before its gate, doesn't touch the ledger and is passed over.
    None when the working ledger's rows for the scene differ from the last
    committed ones (a fact not yet committed: history can't say what it was
    read from), or git has nothing to say."""
    rel = f'reference/{ledger.LEDGER_FILE}'
    try:
        with open(os.path.join(project_dir, rel), encoding='utf-8') as f:
            current = _scene_rows(f.read(), scene_id)
    except (OSError, UnicodeDecodeError):
        return None
    if not current:
        return None
    log = _git_out(project_dir, 'log', '--format=%H', '-n', str(_HISTORY_DEPTH), '--', rel)
    shas = log.decode().split() if log else []

    def rows_at(sha: str) -> list[str] | None:
        out = _git_out(project_dir, 'show', f'{sha}:./{rel}')
        return _scene_rows(out.decode('utf-8', errors='replace'), scene_id) if out else []

    rows = rows_at(shas[0]) if shas else None
    if rows != current:
        return None
    for k, sha in enumerate(shas):
        if k + 1 < len(shas):
            earlier = rows_at(shas[k + 1])
        elif len(shas) == _HISTORY_DEPTH:
            return None   # the change lies further back than we looked
        else:
            earlier = []   # the ledger's first commit
        if rows != earlier:
            out = _git_out(project_dir, 'show', f'{sha}:./scenes/{scene_id}.md')
            return out.decode('utf-8', errors='replace') if out is not None else None
        rows = earlier
    return None


def record_prose(project_dir: str, scene_id: str, prose: str) -> str:
    """Record `prose` as what `scene_id`'s commitments were read from: its
    git blob, written to the object store, in `PROSE_PATH`. Returns why it
    couldn't be ('' when it was); its row goes then, so a later gate never
    diffs against the wrong prose."""
    blob = _git_out(project_dir, 'hash-object', '-w', '--stdin', data=prose.encode('utf-8'))
    blob_id = blob.decode().strip() if blob else ''
    try:
        rows = _prose_rows(project_dir)
    except (OSError, UnicodeDecodeError, ValueError) as e:
        return f'{PROSE_PATH} not updated ({e}); the next re-check counts every reworded fact'
    if blob_id:
        rows[scene_id] = blob_id
    elif rows.pop(scene_id, None) is None:
        return ''   # no git, and nothing recorded to take back
    path = os.path.join(project_dir, PROSE_PATH)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8', newline='') as f:
            f.write('|'.join(_PROSE_COLUMNS) + '\n')
            for sid in sorted(rows):
                f.write(f'{sid}|{rows[sid]}\n')
    except OSError as e:
        return f'{PROSE_PATH} not updated ({e}); the next re-check counts every reworded fact'
    return ''   # no git: the next gate's note says the prose isn't kept


def _paragraphs(text: str) -> list[tuple[str, ...]]:
    return [tuple(_word_list(p)) for p in re.split(r'\n\s*\n', text) if p.strip()]


def _steady_pairs(earlier: str, prose: str) -> dict[int, int]:
    """`steady_paragraphs`, as earlier paragraph index → its index in `prose`."""
    from difflib import SequenceMatcher
    old, new = _paragraphs(earlier), _paragraphs(prose)
    pairs: dict[int, int] = {}
    for tag, i1, i2, j1, _ in SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
        if tag == 'equal':
            for k in range(i2 - i1):
                pairs[i1 + k] = j1 + k
    return {i: j for i, j in pairs.items()
            if (i == 0 and j == 0) or (i > 0 and pairs.get(i - 1) == j - 1)}


def steady_paragraphs(earlier: str, prose: str) -> set[int]:
    """The indexes of `earlier`'s paragraphs that `prose` still has word for
    word (case, punctuation and spacing aside) in the same place: aligned in
    sequence (a moved paragraph is a change), and with the paragraph before
    it unchanged too (the first: still first), since a paragraph reads
    differently after a new antecedent (#558's review)."""
    return set(_steady_pairs(earlier, prose))


def steady_facts(old_rows: list[dict[str, str]], earlier: str, prose: str) -> dict[str, int]:
    """The ids of `old_rows` (commitments read from `earlier`, the prose
    last committed) read from a paragraph `prose` has unchanged and in
    place (`steady_paragraphs`), each with that paragraph's index in
    `prose`: their quote lies within it. A quote not found in `earlier`, or
    across paragraphs, is not steady."""
    paras = _paragraphs(earlier)
    pairs = _steady_pairs(earlier, prose)
    out = {}
    for o in old_rows:
        at = next((j for i, j in pairs.items()
                   if _quote_spans(o.get('quote') or '', list(paras[i]))), None)
        if at is not None:
            out[o['id']] = at
    return out


def _keep_steady(project_dir: str, result: GateResult, old_rows: list[dict[str, str]],
                 prose: str) -> None:
    """#558 (B-032: one deleted phrase, 26 of 27 facts reworded by
    re-extraction and counted as changed, 18 re-checks): keep each earlier
    commitment read from a paragraph the prose still has unchanged and in
    place (`steady_facts`) exactly as it was, same id and statement, and
    drop each proposed row that reads one of them again: its quote lies
    within that same paragraph, and it states the same fact or its quote
    shares four words in a row with the kept one's. A proposed row from any
    other paragraph is never matched to a kept fact (#558's second review:
    a changed paragraph's new fact sharing four words with a kept one was
    dropped, and nothing was re-checked). Only the changed paragraphs'
    facts are new readings, so only they can count as changed. A steady
    fact re-extraction left out is kept too, never dropped silently. Without
    the earlier prose (no git, nothing recorded) nothing is kept, and
    `prose_notes` says so. Runs before the hold-back, which then applies to
    the kept facts too."""
    if not old_rows:
        return
    earlier, why = gated_prose(project_dir, result.scene_id)
    if earlier is None:
        result.prose_notes.append(f'{result.scene_id}: {why}, so every earlier fact the new '
                                  f'reading words differently counts as changed')
        return
    where = steady_facts(old_rows, earlier, prose)
    kept = [copy.deepcopy(o) for o in old_rows if o['id'] in where]
    if not kept:
        return
    new_paras = _paragraphs(prose)

    def again(p: dict[str, str]) -> bool:
        q = p.get('quote') or ''
        at = {j for j, para in enumerate(new_paras) if _quote_spans(q, list(para))}
        if len(at) != 1:
            return False
        j = at.pop()
        qw = _words(q)
        return any(where[o['id']] == j and (
            ledger.fact_key(p) == ledger.fact_key(o)
            or _shared_run(qw, _words(o.get('quote') or '')) >= _MIN_QUOTE_WORDS)
            for o in kept)
    result.proposed = kept + [p for p in result.proposed if not again(p)]
    result.steady = [o['id'] for o in kept]


def _shared_run(a: str, b: str) -> int:
    """The longest run of words two `_words` strings share."""
    from difflib import SequenceMatcher
    aw, bw = a.split(), b.split()
    return SequenceMatcher(None, aw, bw, autojunk=False).find_longest_match(
        0, len(aw), 0, len(bw)).size


def _gone_scenes(project_dir: str) -> set[str]:
    from storyforge.elaborate import get_scenes
    from storyforge.prompts import _GONE
    return {r['id'] for r in get_scenes(os.path.join(project_dir, 'reference'))
            if (r.get('status') or '').strip().lower() in _GONE}


def _has_prose(project_dir: str, scene_id: str) -> bool:
    path = os.path.join(project_dir, 'scenes', f'{scene_id}.md')
    try:
        with open(path, encoding='utf-8') as f:
            return bool(f.read().strip())
    except OSError:
        return False


def _carry_ids(proposed: list[dict[str, str]], old_rows: list[dict[str, str]],
               rows: list[dict[str, str]], scene_id: str) -> None:
    """Give each proposed row that states the same fact as one of the
    scene's earlier commitments (`ledger.fact_key`) that row's id, and its
    end in a later scene when the new row has none: links to it (a later
    `supersedes`, the later scene's end) keep holding. Every other proposed
    row gets an id no other row and no earlier commitment of the scene has
    (extraction chose ids without the old rows, so one may repeat an old id:
    a later link to that id would then land on a different fact), and links
    between proposed rows follow the renames. In place."""
    from storyforge.extract import commitment_id
    by_key: dict[tuple, dict[str, str]] = {}
    for o in old_rows:
        by_key.setdefault(ledger.fact_key(o), o)
    # by position, never by id: a kept steady row (#558) and a new row
    # extraction gave the same id are two rows (Beowulf B-034)
    carry: dict[int, str] = {}
    carried: set[str] = set()
    for i, p in enumerate(proposed):
        o = by_key.get(ledger.fact_key(p))
        if o is None or o['id'] in carried:
            continue
        carried.add(o['id'])
        carry[i] = o['id']
        if not (p.get('resolves') or '').strip() and ledger._ends_elsewhere(o):
            p['resolves'] = o['resolves']
    # an old id not carried is never reused: links to it must not land on
    # a different fact
    taken = {r['id'] for r in rows} | {o['id'] for o in old_rows}
    unchanged = [any(p == o for o in old_rows) for p in proposed]   # kept as it was
    rename: dict[str, str] = {}
    for i, p in enumerate(proposed):
        if i in carry:
            new_id = carry[i]
        elif p['id'] in taken:
            new_id = commitment_id(scene_id, p.get('statement', ''), taken)
        else:
            new_id = p['id']
        if new_id != p['id']:
            rename[p['id']] = new_id
        p['id'] = new_id
        taken.add(new_id)
    # links between extraction's rows follow its renames; a kept row's links
    # are the ledger's and stay
    for p, kept in zip(proposed, unchanged):
        if kept:
            continue
        for col in ('supersedes', 'depends_on'):
            refs = ledger._split(p.get(col, ''))
            if any(r in rename for r in refs):
                p[col] = ';'.join(rename.get(r, r) for r in refs)


# ============================================================================
# Fix (plan §3.2 step 3): targeted edits and a re-check, up to FIX_ROUNDS times
# ============================================================================

FIX_SCHEMA = {
    'type': 'object',
    'properties': {'edits': {'type': 'array', 'items': {
        'type': 'object',
        'properties': {'problem': {'type': 'integer'}, 'find': {'type': 'string'},
                       'replace': {'type': 'string'}},
        'required': ['problem', 'find', 'replace'],
        'additionalProperties': False,
    }}},
    'required': ['edits'],
    'additionalProperties': False,
}


def problems_to_fix(result: GateResult) -> list[str]:
    """What a fix should address, one line each: halts (with the scene's
    words that set the fact), contradictions and broken promises, and
    unverified findings, marked as such with why their quotes failed. An
    extraction problem isn't a prose problem, so it isn't here: the re-check
    extracts again. Neither is a plan conflict (the brief's own words: an
    edit would break the promise) or an inherited contradiction (the
    author's, from before the pass)."""
    proposed = {r['id']: r for r in result.proposed}
    lines = []
    for h in result.halts:
        row = proposed.get(h.fact_id)
        said = (f' The scene says: "{row.get("quote") or row.get("statement")}".'
                if row else '')
        lines.append(f'The scene changes something the book fixed: {h.detail}.{said}')
    for item in result.problems.get('rejected', []):
        lines.append(f'The scene restates a fact the author rejected; change or remove it: '
                     f'{item}')
    for d in result.unruled:
        lines.append(f'UNVERIFIED (extraction thinks the scene changes this; the check gave no '
                     f'ruling; edit only if the scene clearly contradicts it): the plan records '
                     f'"{d.statement}", and the scene says "{d.claim}".')
    for f, unverified in ([(f, False) for f in result.fixable]
                          + [(f, True) for f in result.unverified]):
        tag = (f'UNVERIFIED (the check\'s quotes did not hold up: {f.problem}; edit only '
               f'if the scene clearly contradicts the book) ' if unverified else '')
        if f.kind == 'contradiction':
            lines.append(f'{tag}{f.code} contradiction: the scene says "{f.scene_quote}", '
                         f'but {f.source} establishes "{f.established_quote}". {f.explanation}')
        else:
            lines.append(f'{tag}Broken promise ({f.fact_id}): the brief promises '
                         f'"{f.established_quote}". {f.explanation}'
                         + (f' Nearest words: "{f.scene_quote}".' if f.scene_quote else ''))
    return lines


#: How many rounds `gate_and_fix` runs on a scene that still fails, each a
#: fix and its re-check (or, for a first run with nothing for the fix, a
#: re-roll with no edit). A second round sees what the first changed: one
#: fix often moves a wrong value to another wrong one ("eight days" to
#: "five") or fixes half a pronoun. Not a cap on gate runs: a partial fix
#: (`_partial_fix`) and a re-extraction (`_reextract`, #598) are runs
#: besides the rounds.
FIX_ROUNDS = 2


@dataclass
class FixRound:
    """One fix `gate_and_fix` made: the problems it was sent and its edits."""
    problems: list[str]
    edits: list[dict]


def build_fix_prompt(scene_id: str, prose: str, problems: list[str],
                     protected: list[str] | tuple = (),
                     earlier: list[FixRound] | tuple = ()) -> str:
    """The fix's prompt. `protected`: the brief's own words in the scene
    (`_brief_phrases`), which an edit must leave as they are. `earlier`: the
    fixes already made to this prose, which the check still failed."""
    listing = '\n'.join(f'{n}. {p}' for n, p in enumerate(problems, start=1))
    keep = ''
    if protected:
        keep = ('\n## Lines the brief scripts\n\nThe scene must keep these words exactly; '
                'no edit may change or remove them:\n\n'
                + '\n'.join(f'- "{p}"' for p in protected) + '\n')
    tried = ''
    if earlier:
        parts = []
        for r in earlier:
            parts.append('Problems sent:\n' + '\n'.join(f'- {p}' for p in r.problems))
            parts.append('Edits made:\n' + ('\n'.join(
                f'- "{e.get("find", "")}" became "{e.get("replace", "")}"' for e in r.edits)
                or '- none'))
        tried = ('\n## Earlier fixes\n\nThe scene below already has these edits, and the '
                 'check still found the problems above. Keep what an earlier edit fixed. '
                 'Where an earlier edit put in a value that is still wrong, don\'t guess '
                 'again: take the value the problem quotes from the book, or remove the '
                 'detail. Where it changed only part of something (one pronoun of several, '
                 'one mention of a name), change the rest.\n\n' + '\n\n'.join(parts) + '\n')
    return f"""A continuity check found these problems in scene {scene_id}. Fix each with the smallest edit to the scene's prose that resolves it.

## Problems

{listing}
{keep}{tried}
## Rules

- Change the scene so it agrees with what the book established; never assume the established fact is the one that is wrong. A problem marked UNVERIFIED may be the check's mistake: edit for it only if the scene clearly contradicts the book.
- Take the book's value, never a new one. When a name, number, age, date, duration, place or relationship is wrong, use the one the problem quotes from the book. If the problem doesn't say what the right value is, remove the detail or make it vague ("years ago", "a neighbour") instead of choosing another: any new specific you invent is one more thing that can contradict the book.
- Fix the scene's words, not the book's people: don't rename a character, change who someone is, or move an event to make a contradiction go away.
- A broken promise: add or change the fewest words that deliver it, in the scene's voice, where it fits the action.
- Each edit replaces `find`, words copied exactly from the scene that occur in it once, with `replace`. Keep `find` short: the sentence or clause that changes. Edits must not overlap.
- Change nothing else: no polishing, no other improvements. `problem` is the number of the problem the edit fixes.
- If a problem is a false alarm (the scene does not actually contradict anything), make no edit for it.

## Scene {scene_id}

{prose}"""


def apply_edits(prose: str, edits: list[dict]) -> str:
    """`prose` with each edit's `find` (exactly once in `prose`) replaced.

    Raises:
        GateError: a `find` is missing, occurs more than once, or overlaps
            another edit's; nothing is applied then.
    """
    spans = []
    for e in edits:
        find = (e.get('find') or '').replace('\r\n', '\n')
        if '\r\n' in prose:
            find = find.replace('\n', '\r\n')
        count = prose.count(find) if find else 0
        if count != 1:
            raise GateError(f'a fix edit\'s text occurs {count} times in the scene: '
                            f'{find[:80]!r}')
        start = prose.index(find)
        spans.append((start, start + len(find), e.get('replace') or ''))
    spans.sort()
    for (_, end, _), (start, _, _) in zip(spans, spans[1:]):
        if start < end:
            raise GateError('two fix edits overlap')
    for start, end, replace in reversed(spans):
        prose = prose[:start] + replace + prose[end:]
    return prose


def fix_scene(scene_id: str, prose: str, result: GateResult, *, log_dir: str,
              model: str | None = None, protected: list[str] | tuple = (),
              earlier: list[FixRound] | tuple = (),
              edits_out: list[dict] | None = None) -> str:
    """The scene with targeted edits for `result`'s problems (one model call).
    `earlier`: the fixes already made (`build_fix_prompt`). The edits applied
    are appended to `edits_out` when it is given (only once they all applied;
    nothing when there was nothing to fix).

    Raises:
        GateError: the call failed, the reply was cut off or not the schema,
            or an edit can't be applied (`apply_edits`).
    """
    import json
    from storyforge.api import extract_text, invoke_to_file, is_truncated
    from storyforge.common import select_model
    problems = problems_to_fix(result)
    if not problems:
        return prose
    log_file = os.path.join(log_dir, f'gate-fix-{scene_id}.json')
    try:
        response = invoke_to_file(build_fix_prompt(scene_id, prose, problems, protected,
                                                   earlier),
                                  model or select_model('revision'), log_file, 8000,
                                  output_schema=FIX_SCHEMA, label=f'fix {scene_id}')
        if is_truncated(response):
            raise ValueError('the reply hit its token limit')
        edits = json.loads(extract_text(response))['edits']
    except (RuntimeError, ValueError, KeyError, TypeError) as e:
        raise GateError(f'{scene_id}: the fix failed: {e}') from e
    fixed = apply_edits(prose, edits)
    if edits_out is not None:
        edits_out.extend(edits)
    return fixed


@dataclass
class GatedScene:
    """`gate_and_fix`'s answer: the prose to keep and the gate's last word."""
    prose: str
    result: GateResult          # the last gate run kept (a re-check when there was one)
    first: GateResult           # the first gate run
    # whether .prose differs from the prose given (the caller writes .prose
    # only then); not `bool(rounds)`: a later fix can undo an earlier one
    fixed: bool = False
    rounds: list[FixRound] = field(default_factory=list)  # the fixes kept, in order
    #: what the caller must log: the round discarded and why (its prose and
    #: verdict are not what's kept), and findings a round couldn't place
    notes: list[str] = field(default_factory=list)
    #: the fix round whose fix was discarded (0: none); `rounds` holds the
    #: ones kept, so 1 with no rounds means the scene is as given
    discarded: int = 0
    #: why `BLOCKED_PATH` couldn't be put back to the kept run's
    #: contradictions after a discard ('' when it was): the caller says so
    blocked_stale: str = ''
    #: this invocation's logs (`run_log_dir`): the first run's, each
    #: re-check's in `recheck/`, `recheck-2/` (round 1's re-roll's in
    #: `recheck/`), and `_reextract`'s in `reextract/`
    log_dir: str = ''
    #: whether unchanged prose was gated again for its extraction (round 1's
    #: re-roll, or a re-check failing only on the extractor's misquotes, #598)
    reextracted: bool = False


def _blocking_count(result: GateResult) -> int:
    return len(blocking_lines(report_lines(result)))


def _undone_edit(earlier: list[FixRound] | tuple, before: str, after: str) -> str | None:
    """The `find` of an earlier fix's edit that a later fix put back: words the
    earlier edit removed, absent from `before`, present again in `after`."""
    for r in earlier:
        for e in r.edits:
            find, replace = e.get('find') or '', e.get('replace') or ''
            if find and find not in replace and find not in before and find in after:
                return find
    return None


def _word_list(text: str) -> list[str]:
    from storyforge.checker import normalize
    return re.findall(r'\w+', normalize(text).lower())


class Span(NamedTuple):
    """Words [start, end) of a prose's word list (`_word_list`); an empty
    span marks the place between two words."""
    start: int
    end: int


@dataclass
class _Diff:
    """What a fix changed, as a word diff of the prose before and after it,
    computed once per round (`_diff`): the changed spans on each side
    (words put in, replaced or taken out; an empty span where words were
    only added on the other side)."""
    before: list[str]
    after: list[str]
    before_spans: list[Span]
    after_spans: list[Span]


def _diff(before: str, after: str) -> _Diff:
    from difflib import SequenceMatcher
    old, new = _word_list(before), _word_list(after)
    ops = [op for op in SequenceMatcher(None, old, new, autojunk=False).get_opcodes()
           if op[0] != 'equal']
    return _Diff(old, new, [Span(i1, i2) for _, i1, i2, _, _ in ops],
                 [Span(j1, j2) for _, _, _, j1, j2 in ops])


def _quote_spans(quote: str, words: list[str]) -> list[Span]:
    """Every place `quote` (its parts, split at an ellipsis, in order) is in
    `words`."""
    parts = [p for p in (_word_list(x) for x in re.split(r'\.\.\.|…', quote)) if p]
    if not parts:
        return []

    def at(part: list[str], start: int) -> int:
        for i in range(start, len(words) - len(part) + 1):
            if words[i:i + len(part)] == part:
                return i
        return -1
    out, first = [], parts[0]
    for i in range(len(words) - len(first) + 1):
        if words[i:i + len(first)] != first:
            continue
        end, ok = i + len(first), True
        for part in parts[1:]:
            j = at(part, end)
            if j < 0:
                ok = False
                break
            end = j + len(part)
        if ok:
            out.append(Span(i, end))
    return out


#: How many unchanged words must lie between a quote and every change for
#: the quote to count as away from the fix (`_touches(near=True)`): a word
#: diff can line a change up a word or two off where the edit was
#: ("forty-one, the morning after. The coffee" against "forty-one. The
#: coffee" matches the two "the"s). Tuned on a handful of E4/E8 replays
#: (2026-11-03), not measured
_NEAR_WORDS = 4


def _touches(span: Span, changed: list[Span], near: bool = False) -> bool:
    """Whether `span` overlaps a changed span (an empty one: lies strictly
    inside it); with `near`, whether fewer than `_NEAR_WORDS` unchanged
    words lie between it and a changed span."""
    s, e = span
    if near:
        return any(a - _NEAR_WORDS < e and s < b + _NEAR_WORDS for a, b in changed)
    return any((a < e and s < b) if a < b else (s < a < e) for a, b in changed)


def _in_edited_text(f: Finding, changed: list[Span], words: list[str]) -> bool:
    """Whether `f`'s scene quote lies in text the fix changed: found in
    `words`, and every place it is found touches a changed span (an empty
    one, words taken out, when the quote spans it). A quote not found: no."""
    places = _quote_spans(f.scene_quote, words)
    return bool(places) and all(_touches(p, changed) for p in places)


def _in_untouched_text(f: Finding, changed: list[Span], words: list[str]) -> bool:
    """Whether `f`'s scene quote lies only in text the fix left alone: found
    in `words`, and no place it is found comes near a changed span
    (`_touches(near=True)`: words put in right after a quote may be its
    fix). A quote not found: no (it may be about the change)."""
    places = _quote_spans(f.scene_quote, words)
    return bool(places) and not any(_touches(p, changed, near=True) for p in places)


def _unplaced(run: GateResult, words: list[str]) -> list[Finding]:
    """`run`'s blocking findings whose scene quote is blank or not found in
    `words` (an unverified quote, a paraphrase, a promise with no nearest
    words): they can't be placed relative to the fix."""
    return [f for f in run.findings + run.unverified if not _quote_spans(f.scene_quote, words)]


def _persists(f: Finding, earlier: list[Finding]) -> bool:
    """Whether `f` is a problem the run before the fix already had: the same
    target (`checker.same_target`, a contradiction with no source only on a
    fact id both name): the same promise, or the same source and
    established words. The scene quote and code are not compared: the fix
    changed the one, and readings vary on the other. A contradiction with
    the same file or calendar but other established words (a fix that
    swaps one wrong date for another against another line) is a new one.

    `earlier` includes the run's inherited findings: a problem already in
    the book that the fix's words restate is that problem, not the fix's."""
    from storyforge.checker import same_target
    return any(same_target(f, g, need_fact=True) for g in earlier)


def _introduced(before_run: GateResult, after_run: GateResult, diff: _Diff) -> list[Finding]:
    """The blocking findings of `after_run` (the gate run on the fixed
    prose) that the fix brought in, not a problem `before_run` already had
    (`_persists`) and either:

    - in words the fix changed (`_in_edited_text`), or
    - a broken promise (CR-2, #504's review) whose quote can't be placed or
      isn't away from the fix: a fix that takes out the words keeping a
      promise leaves nothing to quote.

    A finding in words the fix left alone is not the fix's, however new:
    two readings of the same words differ (E8, 2026-11-01). Nor is a new
    contradiction whose quote can't be placed: nothing ties it to the
    edits (two readings make different unverified findings too); it still
    counts in `_worse`'s total, and the caller is told it couldn't be
    placed."""
    if not after_run.check or not diff.after_spans:
        return []
    earlier = list(before_run.check.findings + before_run.check.unverified
                   if before_run.check else [])
    out = []
    for f in after_run.findings + after_run.unverified:
        if _persists(f, earlier):
            continue
        if _in_edited_text(f, diff.after_spans, diff.after):
            out.append(f)
        elif f.kind == 'broken-promise' and not _in_untouched_text(f, diff.after_spans,
                                                                   diff.after):
            out.append(f)
    return out


def _worse(n: int, before_run: GateResult, after_run: GateResult, diff: _Diff) -> str:
    """Why fix round `n`'s prose (which failed as `after_run`) is worse
    than the prose it fixed (failed as `before_run`), or '' when it isn't:
    more blocking problems, or a problem the fix brought in (`_introduced`).

    The count leaves out, on each side, the findings whose quotes lie only
    in words the fix left alone (`_in_untouched_text`): those words are in
    both proses, and two readings of them differ. E4's missing-persons
    (2026-11-03): a fix cleared both first findings, the re-check found
    four new ones, every one in words it hadn't touched, and a plain count
    would have thrown the fix away. A finding that can't be placed counts."""
    then_alone = sum(_in_untouched_text(f, diff.before_spans, diff.before)
                     for f in before_run.findings + before_run.unverified)
    now_alone = sum(_in_untouched_text(f, diff.after_spans, diff.after)
                    for f in after_run.findings + after_run.unverified)
    then = _blocking_count(before_run) - then_alone
    now = _blocking_count(after_run) - now_alone
    if now > then:
        alone = (f' (not counting {then_alone} and {now_alone} in words it left alone)'
                 if then_alone or now_alone else '')
        return f'fix round {n} left {now} problem(s), more than the {then} before it{alone}'
    new = _introduced(before_run, after_run, diff)
    if new:
        return (f'fix round {n} brought in {len(new)} problem(s) ('
                + '; '.join(_one_line(f.message())[:200] for f in new[:3])
                + (' ...' if len(new) > 3 else '') + ')')
    return ''


def _edit_span(prose_words: list[str], replace: str) -> list[Span]:
    """Where an edit's replacement lies in the fixed prose's words."""
    return _quote_spans(replace, prose_words) if _word_list(replace) else []


def _bad_edits(edits: list[dict], new: list[Finding], after_words: list[str]) -> list[int] | None:
    """The indexes of `edits` that brought in `new` (`_introduced`'s
    findings), or None when one can't be tied to an edit: a finding whose
    scene quote lies in or next to an edit's replacement, or a broken
    promise whose promised words the edit took out (its `find` shares four
    words in a row with them)."""
    bad: set[int] = set()
    for f in new:
        hit = set()
        places = _quote_spans(f.scene_quote, after_words) if f.scene_quote else []
        for i, e in enumerate(edits):
            spans = _edit_span(after_words, e.get('replace') or '')
            if places and any(_touches(p, spans, near=True) for p in places):
                hit.add(i)
            elif (f.kind == 'broken-promise' and f.established_quote
                  and _shares_run(_words(e.get('find') or ''), _words(f.established_quote))):
                hit.add(i)
        if not hit:
            return None
        bad |= hit
    return sorted(bad)


def _shares_run(a: str, b: str, n: int = 4) -> bool:
    """Whether two `_words` strings share a run of `n` words."""
    aw, bw = a.split(), b.split()
    runs = {tuple(aw[i:i + n]) for i in range(len(aw) - n + 1)}
    return any(tuple(bw[i:i + n]) in runs for i in range(len(bw) - n + 1))


def _partial_fix(project_dir: str, scene_id: str, command: str, current: str,
                 before_run: GateResult, after_run: GateResult, diff: '_Diff',
                 edits: list[dict], *, log_dir: str, extract_model, check_model,
                 before) -> tuple[list[dict], str, GateResult, str] | None:
    """B-030 (#556): a fix round with several edits, discarded because it
    brought in problems, is retried with only the edits that didn't
    (`_bad_edits`), one more gate run. Returns (the edits kept, their
    prose, its gate run, the dropped edits as text), or None when every
    edit (or none) is to blame, a new problem can't be tied to one, the
    rest can't be applied, the run fails, or it is worse than `before_run`
    (`_worse`)."""
    if len(edits) < 2:
        return None
    new = _introduced(before_run, after_run, diff)
    if not new:
        return None   # worse by count alone: nothing to tie to an edit
    bad = _bad_edits(edits, new, diff.after)
    if not bad or len(bad) == len(edits):
        return None
    good = [e for i, e in enumerate(edits) if i not in bad]
    try:
        prose = apply_edits(current, good)
        run = gate_scene(project_dir, scene_id, command=command, prose=prose,
                         log_dir=log_dir, extract_model=extract_model,
                         check_model=check_model, before=before)
    except GateError:
        return None
    if not run.passed and _worse(0, before_run, run, _diff(current, prose)):
        return None
    dropped = '; '.join(f'"{_one_line(edits[i].get("find", ""))[:60]}"' for i in bad)
    return good, prose, run, dropped


def run_log_dir(log_dir: str, scene_id: str, *, now=None, pid: int | None = None) -> str:
    """A new directory, created, for one gate invocation's logs of
    `scene_id`: `log_dir/<scene>/<YYYYMMDD-HHMMSS>-<pid>`, with `-2`, `-3`
    ... when that is taken. Callers pass a fixed `log_dir` (write's
    working/logs/gate, check's working/logs/check), and the log files are
    named by scene alone (gate-check-<scene>.json), so without it a later
    run of the scene, or a re-check of it in the same run, overwrote the
    record of what the earlier one was told and changed.

    The directory is made exclusively (`os.mkdir`), so two calls never share
    one, whatever the clock. `now` (a datetime) and `pid` are for tests.

    Raises:
        GateError: the directory can't be made (SF-5, #504's review: a
            traceback named nothing); nothing was run.
    """
    from datetime import datetime
    stamp = f'{(now or datetime.now()):%Y%m%d-%H%M%S}-{os.getpid() if pid is None else pid}'
    parent = os.path.join(log_dir, scene_id)
    base = os.path.join(parent, stamp)
    path, n = base, 1
    try:
        os.makedirs(parent, exist_ok=True)
        while True:
            try:
                os.mkdir(path)
                return path
            except FileExistsError:
                n += 1
                path = f'{base}-{n}'
    except OSError as e:
        raise GateError(f'{scene_id}: can\'t make the gate log directory {path}: {e}') from e


def gate_and_fix(project_dir: str, scene_id: str, *, command: str, prose: str,
                 log_dir: str, extract_model: str | None = None,
                 check_model: str | None = None, fix_model: str | None = None,
                 before: Snapshot | None = None) -> GatedScene:
    """Gate `prose`; while it doesn't pass, fix it and gate the fixed prose,
    at most `FIX_ROUNDS` times (plan §3.2 step 3). Each fix after the first is
    sent the earlier fixes' problems and edits (`rounds`, `build_fix_prompt`).

    - A first run with nothing for the fix (`problems_to_fix` empty: it
      failed on extraction problems, which aren't sent to the fix) and no
      plan conflicts is re-gated without an edit, so extraction runs again.
      That re-roll counts as a round and logs to `recheck/`.
    - A later run with nothing for the fix stops, unless all that stopped
      it is the extractor's slips (`_only_extractor_slips`: a quote not in
      the prose or none, with no halt, other extraction problem, finding,
      plan conflict, unverified finding or unruled dispute; #598). Then the
      same prose is gated again (`_reextract`: extraction and the check;
      logged; in `reextract/`; not a round), and so is the last round's
      re-check when only slips stopped it. That is at most once per
      invocation (`_OneRegate`), round 1's re-roll included: a first run
      failing on slips alone is extracted twice, not three times. What the
      re-extraction's run finds instead goes to the next round's fix while
      one is left; after the last round it is the verdict. A run that
      misquotes again is kept and reported (never fuzzy-matched to the
      prose's words: one word can change the fact); one that can't finish
      keeps the run before it.
    - A run with real problems beside slips goes to the fix, not a
      re-extraction: the fix's re-check extracts the edited prose anyway.
    - A run with plan conflicts and nothing for the fix (extraction problems
      or not) is neither fixed nor re-gated: they are the author's (the brief
      disagrees with the book), and a re-roll that missed one would pass
      prose that has it.
    - `before` (the book before the pass, `snapshot`) goes to every run
      (`gate_scene`): an inherited contradiction doesn't block any of them.
    - A fix that changes nothing (every problem judged a false alarm) is not
      re-gated: the last verdict stands, and a re-roll of the same prose
      won't overturn it.
    - Every round, the first included: a fix whose run fails worse than
      the run before it (`_worse`: more blocking problems near the change,
      or a problem it brought in, `_introduced`) is discarded (mended-bridle,
      2026-11-03: the first fix made a scene that agreed with its brief
      match a later scene's error, and its re-check, fewer problems in all,
      was kept). The prose and verdict before it are kept, `BLOCKED_PATH`
      is put back to that run's contradictions (`.blocked_stale` when it
      can't be), and `.discarded` names the round. A first fix discarded
      leaves the prose as given (`.fixed` False). A run that passed is
      always kept (it committed), and so is a re-gate with no edit (the
      same prose).
    - Round 2 on: the fix is also discarded, the earlier prose and verdict
      kept, when the fix or its check fails (`GateError`; in round 1 that
      raises, there being no fixed prose to keep) or it puts back words an
      earlier fix removed (checked before its gate run, which would commit
      on a lucky pass).
    - Each discard, and each round's findings it couldn't place, is in
      `.notes` for the caller to log.
    - Otherwise the prose kept is the last gated, with that run's verdict.

    The caller must write `.prose` to the scene file at once, whether or not
    `.result.passed`: when it passed, the ledger was already committed with
    quotes from that prose.

    Raises:
        GateError: from the first gate run, the first fix or its re-gate; it
            carries the first run as `.first` (None when the first run itself
            failed), so its findings can still be reported, and the logs as
            `.log_dir`.

    Logs: each invocation writes to its own `run_log_dir(log_dir,
    scene_id)` (`.log_dir`), so a later gate of the scene never overwrites
    this one's.
    """
    from storyforge import api
    logs = run_log_dir(log_dir, scene_id)
    first = None
    try:
        first = gate_scene(project_dir, scene_id, command=command, prose=prose, log_dir=logs,
                           extract_model=extract_model, check_model=check_model,
                           before=before)
        current, result, rounds, notes, run_dir = prose, first, [], [], logs
        discarded, blocked_stale = 0, ''
        regate = _OneRegate()
        for n in range(1, FIX_ROUNDS + 1):
            if result.passed:
                break
            if n > 1 and _only_extractor_slips(result) and regate.take():
                result, run_dir = _reextract(
                    project_dir, scene_id, command, current, result, logs, notes,
                    extract_model=extract_model, check_model=check_model, before=before,
                    fallback_dir=run_dir)
                if result.passed:
                    break
            to_fix = problems_to_fix(result)
            if not to_fix and (result.plan_conflicts or n > 1):
                break
            # round 1 with nothing for the fix: re-gate the same prose
            reroll = not to_fix
            if reroll:
                regate.take()   # the first take: always granted
                if _only_extractor_slips(result):
                    _say_misquoted(scene_id, result)
            kept = ('the prose as given and the first verdict' if n == 1
                    else 'the prose and verdict before it')
            # the brief's own words the scene has: the fix must keep them
            protected = [p for p in _brief_phrases(project_dir, scene_id)
                         if _quoted_in(p, current)]
            edits: list[dict] = []
            try:
                with api.metered() as meter:
                    try:
                        fixed = fix_scene(scene_id, current, result, log_dir=run_dir,
                                          model=fix_model, protected=protected,
                                          earlier=tuple(rounds), edits_out=edits)
                    finally:
                        _log_spend(meter, project_dir, 'gate-fix', scene_id)
            except GateError as e:
                if n == 1:
                    raise
                notes.append(f'fix round {n} failed ({e}); kept {kept}')
                discarded = n
                break
            if to_fix and fixed == current:
                break
            undone = _undone_edit(rounds, current, fixed) if n > 1 else None
            if undone:
                notes.append(f'fix round {n} put back words an earlier fix removed '
                             f'("{_one_line(undone)[:80]}"); kept {kept}')
                discarded = n
                break
            # each run's log (and the fix that read it) in its own directory:
            # logs, logs/recheck, logs/recheck-2
            next_dir = os.path.join(logs, 'recheck' if n == 1 else f'recheck-{n}')
            try:
                again = gate_scene(project_dir, scene_id, command=command, prose=fixed,
                                   log_dir=next_dir, extract_model=extract_model,
                                   check_model=check_model, before=before)
            except GateError as e:
                if n == 1:
                    raise
                notes.append(f'the check after fix round {n} failed ({e}); kept {kept}')
                discarded = n
                break
            # never worse, the first round included (mended-bridle, 2026-11-03:
            # round 1 made a correct scene match another scene's error, and its
            # re-check's broken promise, in the words it changed, was kept).
            # A pass is kept: it committed. A re-roll with no edit is the
            # same prose, so its verdict stands
            worse, loose = '', ''
            if fixed != current and not again.passed:
                diff = _diff(current, fixed)
                worse = _worse(n, result, again, diff)
                # SF-3 (#504's review): a new problem that can't be placed is
                # neither tied to the fix nor cleared of it: say so
                earlier = (result.check.findings + result.check.unverified
                           if result.check else [])
                unplaced = [f for f in _unplaced(again, diff.after)
                            if f.kind != 'broken-promise' and not _persists(f, earlier)]
                if unplaced:
                    loose = (f'fix round {n}: {len(unplaced)} new finding(s) of the check '
                             f'after it could not be placed in the fixed prose ('
                             + ', '.join(f'{f.code} vs {f.source}' for f in unplaced[:5])
                             + '): judged by the problem count only')
            if worse:
                # B-030 (#556): keep the edits that didn't do it
                part = _partial_fix(project_dir, scene_id, command, current, result, again,
                                    diff, edits, log_dir=os.path.join(logs, f'partial-{n}'),
                                    extract_model=extract_model, check_model=check_model,
                                    before=before)
                if part is not None:
                    good, part_prose, part_run, dropped_edits = part
                    notes.append(f'{worse}; kept its {len(good)} edit(s) that did not, '
                                 f'dropped {dropped_edits}, and re-checked')
                    rounds.append(FixRound(to_fix, good))
                    current, result, run_dir = part_prose, part_run, os.path.join(
                        logs, f'partial-{n}')
                    if part_run.passed:
                        break
                    continue
                notes.append(f'{worse}; kept {kept}')
                discarded = n
                if loose:
                    notes.append(loose)
                # the blocked list is the kept run's, for `check --accept`
                blocked_stale = _note_blocked(project_dir, scene_id, command, result)
                if blocked_stale:
                    notes.append(f'WARNING: {blocked_stale}; it lists the discarded fix\'s '
                                 f'contradictions, which `check --accept` refuses')
                break
            if loose:
                notes.append(loose)
            if fixed != current:
                rounds.append(FixRound(to_fix, edits))
            current, result, run_dir = fixed, again, next_dir
        # the last round's re-check failed only on the extractor's slips. A
        # discard needs no guard: the run it keeps had problems for the fix
        # (it was fixed), so never slips only
        if _only_extractor_slips(result) and regate.take():
            result, run_dir = _reextract(
                project_dir, scene_id, command, current, result, logs, notes,
                extract_model=extract_model, check_model=check_model, before=before,
                fallback_dir=run_dir)
    except GateError as e:
        e.first, e.log_dir = first, logs
        raise
    return GatedScene(current, result, first, fixed=current != prose, rounds=rounds,
                      notes=notes, log_dir=logs, discarded=discarded,
                      blocked_stale=blocked_stale, reextracted=regate.taken)


#: Extraction problems that are the extractor's own slip, never the prose's:
#: a quote that isn't in the scene (`extract.commitment_rows` checks it
#: against the prose), or no quote at all. No prose edit repairs one, so
#: the fix is never sent them (`problems_to_fix`)
_EXTRACTOR_SLIPS = (MISQUOTE, NO_QUOTE)


class _OneRegate:
    """The one gate run of unchanged prose a `gate_and_fix` call may make for
    its extraction (#598): round 1's re-roll or `_reextract`. `take()`
    claims it: True the first time, False after; `taken` says whether it
    was."""

    def __init__(self) -> None:
        self.taken = False

    def take(self) -> bool:
        if self.taken:
            return False
        self.taken = True
        return True


def _only_extractor_slips(result: GateResult) -> list[str]:
    """The extractor's slips (`_EXTRACTOR_SLIPS`, as `unresolved` lists
    them) when they are all that stopped `result`; [] when it passed or
    anything else blocks (a halt, another extraction problem, a finding, a
    plan conflict, an unverified finding, an unruled dispute)."""
    if (result.passed or result.halts or result.findings or result.unverified
            or result.unruled):
        return []
    if any(result.problems.get(k) for k in UNRESOLVED if k not in _EXTRACTOR_SLIPS):
        return []
    return [f'{k}: {item}' for k in _EXTRACTOR_SLIPS for item in result.problems.get(k, [])]


def _say_misquoted(scene_id: str, run: GateResult) -> None:
    """The log line for a re-extraction (#598): what the extractor misquoted."""
    from storyforge.common import log
    slips = _only_extractor_slips(run)
    log(f'  {scene_id}: the extractor misquoted the prose ({len(slips)} quote(s) not in the '
        f'scene: {_one_line("; ".join(slips))[:200]}); re-running extraction on the same prose')


def _reextract(project_dir: str, scene_id: str, command: str, prose: str, run: GateResult,
               logs: str, notes: list[str], *, extract_model: str | None,
               check_model: str | None, before: Snapshot | None,
               fallback_dir: str) -> tuple[GateResult, str]:
    """#598 (Telemachy, 2026-11-05): a re-check after a fix failed only on a
    quote the extractor changed ("she would sit" for the prose's "he would
    sit"); the fix edits prose, so it had nothing to do, and `write
    --keep-going` stopped (`can_commit_provisionally`: a commit would write
    the wrong quote). Gate the same `prose` again with `gate_scene`: the
    whole run, extraction and every reading of the check (its spend is a
    `gate` row like any run's), not extraction alone, so the check rules on
    the new extraction's disputes. Return that run and its log directory
    (`logs/reextract`). The quote is never replaced by the prose's words:
    one word (he/she) can change the fact.

    The run that comes back is kept, a verdict on the same prose: a pass
    has committed; one stopped by slips alone again is said in `notes`,
    its mismatches reported; one stopped by anything else (a finding this
    check makes, or a halt or other problem the new extraction brings) goes
    to the next round's fix while `gate_and_fix` has one left, and after
    the last round is the verdict. A run that raises `GateError` keeps `run`
    and `fallback_dir`, said in `notes`."""
    _say_misquoted(scene_id, run)
    run_dir = os.path.join(logs, 'reextract')
    try:
        again = gate_scene(project_dir, scene_id, command=command, prose=prose,
                           log_dir=run_dir, extract_model=extract_model,
                           check_model=check_model, before=before)
    except GateError as e:
        notes.append(f're-running extraction on the same prose failed ({e}); kept the '
                     f'verdict before it')
        return run, fallback_dir
    if _only_extractor_slips(again):
        notes.append('extraction re-run on the same prose misquoted it again; the quote '
                     'mismatches are reported, not replaced with the prose\'s words')
    return again, run_dir


def _one_line(text: str) -> str:
    return ' '.join(str(text).split())


#: `report_lines`' prefixes for what is reported either way, not what
#: stopped the commit
_NOT_BLOCKING = ('NOTE', 'COMMITTED', 'ALREADY IN THE SCENE', 'SOURCE BACKS THIS SCENE')


def blocking_lines(lines: list[str]) -> list[str]:
    """The `report_lines` that name what stopped the commit."""
    return [line for line in lines if not line.startswith(_NOT_BLOCKING)]


def _from_reading(f: Finding) -> str:
    """Which reading made `f`, past the first (its exchange is in
    gate-check-<scene>.rN.json, beside the first reading's log)."""
    return f' [reading {f.reading}]' if f.reading > 1 else ''


def report_lines(result: GateResult) -> list[str]:
    """The gate's verdict on a scene as one-line strings (log lines, list
    items): everything that stopped the commit, then what is reported
    either way, then what was committed."""
    lines = []
    for h in result.halts:
        lines.append(f'HALT ({h.kind}): {_one_line(h)}')
    for item in result.unresolved:
        lines.append(f'EXTRACTION: {_one_line(item)}')
    for f in result.findings:
        if _among(f, result.plan_conflicts):
            note = next((n for g, n in result.speaker_notes if g is f), '')
            lines.append(f'PLAN CONFLICT (the brief\'s own words contradict the book; fix the '
                         f'brief or {f.source}){_from_reading(f)}: {_one_line(f.message())}'
                         + (f' ({_one_line(note)})' if note else ''))
        else:
            lines.append(f'{f.kind.upper()}{_from_reading(f)}: {_one_line(f.message())}')
    for f in result.unverified:
        lines.append(f'UNVERIFIED ({f.problem}){_from_reading(f)}: '
                     f'{_one_line(f.message())}')
    for d in result.unruled:
        lines.append(f'UNRULED: the scene may change the plan\'s {d.fact_id} '
                     f'("{_one_line(d.statement)}"): "{_one_line(d.claim)}"; the check gave '
                     f'no ruling')
    for f, why in result.source_backed:
        lines.append(f'SOURCE BACKS THIS SCENE (not blocking; {f.source} is listed for the '
                     f'author in {PENDING_PATH}): {_one_line(f.message())} — the source: '
                     f'{_one_line(why)}')
    if result.source_superseded:
        lines.append('NOTE (no longer binding: the source backs this scene against them): '
                     + ', '.join(result.source_superseded))
    if result.source_dropped:
        lines.append('NOTE (not recorded: the source contradicts it): '
                     + '; '.join(f'{_one_line(st)} ({_one_line(why)})'
                                 for st, why in result.source_dropped))
    for note in result.source_notes:
        lines.append(f'NOTE (source): {_one_line(note)}')
    for f in result.inherited:
        lines.append(f'ALREADY IN THE SCENE (before this pass, or reported before; not '
                     f'blocking, the author\'s to fix; listed in {REPORTED_PATH} on commit): '
                     f'{_one_line(f.message())}')
    if result.held_back:
        lines.append(('NOTE (not recorded: states what stopped the commit): '
                      if result.provisional else
                      'NOTE (not recorded: states a contradiction already in the scene): ')
                     + '; '.join(_one_line(st) for st, _ in result.held_back))
    if result.check:
        for d in result.check.cleared:
            lines.append(f'NOTE (plan fact kept, link not applied; the check found no '
                         f'contradiction): {d.fact_id} ("{_one_line(d.statement)}") vs '
                         f'"{_one_line(d.claim)}"')
    for kind in REPORTED:
        if kind in ('disagrees', 'ends registry'):
            continue    # every one is a dispute: a finding, UNRULED or the note above
        items = result.problems.get(kind, [])
        if items:
            lines.append(f'NOTE ({_REPORTED_LABEL.get(kind, kind)}): '
                         + '; '.join(_one_line(i) for i in items[:20])
                         + (' ...' if len(items) > 20 else ''))
    if result.check:
        for rid, quote, why in result.check.kept_unverified:
            lines.append(f'NOTE (kept, not filled): {rid}: {why}')
        if result.check.unknown_brief_items:
            lines.append('NOTE (brief items in words, no ledger fact; checked as words): '
                         + _one_line('; '.join(result.check.unknown_brief_items)))
        if result.check.plan_departures:
            lines.append('NOTE (the prose departs from planned facts; not an error, they '
                         'stay planned): ' + _one_line('; '.join(
                             f'{f.fact_id}: {f.explanation or f.kind}'
                             for f in result.check.plan_departures)))
        if result.check.stale_brief_items:
            lines.append('NOTE (brief items naming a fact that is not binding; not checked, '
                         'fix the brief): ' + _one_line('; '.join(result.check.stale_brief_items)))
    if result.dropped:
        lines.append(f'NOTE (not recorded, judged not to last beyond the scene): '
                     + '; '.join(f'{_one_line(st)} ({_one_line(why)})'
                                 for st, why in result.dropped[:20])
                     + (' ...' if len(result.dropped) > 20 else ''))
    if result.steady:
        lines.append(f'NOTE (kept as they were, read from paragraphs the prose has unchanged): '
                     f'{len(result.steady)} fact(s)')
    for note in result.prose_notes:
        lines.append(f'NOTE (re-check): {_one_line(note)}')
    if result.committed:
        lines.append(f'COMMITTED{" (provisionally: listed " + PENDING_PATH + ")" if result.provisional else ""}: {len(result.proposed)} fact(s)'
                     + (f'; quotes filled: {", ".join(result.quotes_filled)}'
                        if result.quotes_filled else ''))
    return lines


# ============================================================================
# Scenes waiting on the gate: working/gate-pending.csv
# ============================================================================

#: Scenes whose prose is on disk but didn't pass the gate, so their facts
#: aren't in the ledger. `write` won't draft a scene after one (it would be
#: drafted from an incomplete ledger); a pass, through `write` or
#: `storyforge check`, takes it off.
PENDING_PATH = 'working/gate-pending.csv'
_PENDING_COLUMNS = ['scene_id', 'command', 'reason']


def _pending_file(project_dir: str) -> str:
    return os.path.join(project_dir, PENDING_PATH)


def pending(project_dir: str) -> dict[str, dict[str, str]]:
    """Scene id → {scene_id, command, reason} for each scene waiting on the gate."""
    path = _pending_file(project_dir)
    if not os.path.isfile(path):
        return {}
    with open(path, encoding='utf-8') as f:
        lines = [line.rstrip('\n') for line in f if line.strip()]
    if not lines or lines[0].split('|') != _PENDING_COLUMNS:
        raise GateError(f'{PENDING_PATH}: the header must be {"|".join(_PENDING_COLUMNS)}')
    out = {}
    for line in lines[1:]:
        cells = line.split('|')
        if len(cells) != len(_PENDING_COLUMNS):
            raise GateError(f'{PENDING_PATH}: a row with {len(cells)} cells: {line[:80]!r}')
        out[cells[0]] = dict(zip(_PENDING_COLUMNS, cells))
    return out


def _write_pending(project_dir: str, rows: dict[str, dict[str, str]]) -> None:
    path = _pending_file(project_dir)
    if not rows:
        if os.path.isfile(path):
            os.remove(path)
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='') as f:
        f.write('|'.join(_PENDING_COLUMNS) + '\n')
        for row in rows.values():
            f.write('|'.join(row[c] for c in _PENDING_COLUMNS) + '\n')


def mark_pending(project_dir: str, scene_id: str, command: str, reason: str) -> None:
    """List `scene_id`. A `REVISE_REJECTED` row keeps that command and its
    rejected fact ids whatever replaces it (a failed check of the revision):
    the ids are what lists the dependents once the scene passes."""
    from storyforge.common import csv_safe
    rows = pending(project_dir)
    old = rows.get(scene_id)
    ids = rejected_ids(old) + (rejected_ids({'command': command, 'reason': reason})
                               if command == REVISE_REJECTED else [])
    if old and old.get('command') == PROVISIONAL and command == 'advisor':
        # #556's review: a failed check of a provisional scene leaves its
        # provisional facts in the ledger; it is still provisional
        command = PROVISIONAL
    if ids:
        command = REVISE_REJECTED
        reason = re.sub(r'\s*\[rejected: [^\]]*\]', '', reason) \
            + f' [rejected: {";".join(dict.fromkeys(ids))}]'
    rows[scene_id] = {'scene_id': scene_id, 'command': command, 'reason': csv_safe(reason)}
    _write_pending(project_dir, rows)


def rejected_ids(row: dict[str, str] | None) -> list[str]:
    """The rejected fact ids a `REVISE_REJECTED` pending row carries."""
    if not row or row.get('command') != REVISE_REJECTED:
        return []
    ids = [i for group in re.findall(r'\[rejected: ([^\]]*)\]', row.get('reason', ''))
           for i in group.split(';') if i]
    return list(dict.fromkeys(ids))


def clear_pending(project_dir: str, scene_id: str) -> None:
    rows = pending(project_dir)
    if rows.pop(scene_id, None) is not None:
        _write_pending(project_dir, rows)


# ============================================================================
# Errors already in the book: working/gate-reported.csv
# ============================================================================

#: The contradictions a gate run found already in the book (`inherited`)
#: and let through, one row each, so the author has them after the run's
#: log scrolls by. Not a block: `write` and `revise` go on past them. A
#: scene's rows are replaced each time it commits; a gate run of the scene
#: that finds one of them again (same source and quote, any command) counts
#: it inherited. Rows whose `command` is `ACCEPTED` are the author's
#: (`storyforge check --accept`): they survive the replacement, so a check
#: that happens not to raise one doesn't forget it (the checker's findings
#: vary run to run), and go only when their quote leaves the scene's prose.
REPORTED_PATH = 'working/gate-reported.csv'
_REPORTED_COLUMNS = ['scene_id', 'command', 'source', 'quote', 'finding']
#: The `command` of a row the author accepted (`storyforge check --accept`)
ACCEPTED = 'accepted'
#: The verified contradictions that stopped each scene's last gate run, the
#: rows `storyforge check --accept` moves to `REPORTED_PATH` (Ben,
#: 2026-11-02: a stop on an error in the book is the author's to fix or
#: accept). Same columns; replaced by each gate run of the scene that gets
#: to the check, put back to the kept run's when `gate_and_fix` discards a
#: fix, and cleared when it commits.
BLOCKED_PATH = 'working/gate-blocked.csv'


def _read_rows(project_dir: str, rel: str) -> dict[str, list[dict[str, str]]]:
    path = os.path.join(project_dir, rel)
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding='utf-8') as f:
            lines = [line.rstrip('\n') for line in f if line.strip()]
    except (OSError, UnicodeDecodeError) as e:
        raise GateError(f'{rel}: {e}') from e
    if not lines or lines[0].split('|') != _REPORTED_COLUMNS:
        raise GateError(f'{rel}: the header must be {"|".join(_REPORTED_COLUMNS)}')
    out: dict[str, list[dict[str, str]]] = {}
    for line in lines[1:]:
        cells = line.split('|')
        if len(cells) != len(_REPORTED_COLUMNS):
            raise GateError(f'{rel}: a row with {len(cells)} cells: {line[:80]!r}')
        row = dict(zip(_REPORTED_COLUMNS, cells))
        out.setdefault(row['scene_id'], []).append(row)
    return out


def _write_rows(project_dir: str, rel: str, rows: dict[str, list[dict[str, str]]]) -> None:
    """Write `rows` to `rel`; the file goes when there are none."""
    path = os.path.join(project_dir, rel)
    if not any(rows.values()):
        if os.path.isfile(path):
            os.remove(path)
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='') as f:
        f.write('|'.join(_REPORTED_COLUMNS) + '\n')
        for sid in sorted(rows):
            for row in rows[sid]:
                f.write('|'.join(row[c] for c in _REPORTED_COLUMNS) + '\n')


def _finding_rows(scene_id: str, command: str, findings: list[Finding]) -> list[dict[str, str]]:
    from storyforge.common import csv_safe
    return [{'scene_id': scene_id, 'command': command,
             'source': csv_safe(f.established_scene or ''),
             'quote': csv_safe(_one_line(f.scene_quote)),
             'finding': csv_safe(_one_line(f.message()))} for f in findings]


def _same(a: dict[str, str], b: dict[str, str]) -> bool:
    """Whether two rows are the same finding, as `_classify` matches one:
    the same source and quote."""
    return a['source'] == b['source'] and _words(a['quote']) == _words(b['quote'])


def reported(project_dir: str) -> dict[str, list[dict[str, str]]]:
    """Scene id → its rows in `REPORTED_PATH`.

    Raises:
        GateError: the file is malformed or unreadable.
    """
    return _read_rows(project_dir, REPORTED_PATH)


def blocked(project_dir: str) -> dict[str, list[dict[str, str]]]:
    """Scene id → its rows in `BLOCKED_PATH` (`GateError` as `reported`)."""
    return _read_rows(project_dir, BLOCKED_PATH)


def record_reported(project_dir: str, scene_id: str, command: str,
                    findings: list[Finding], prose: str | None = None) -> None:
    """Replace `scene_id`'s rows in `REPORTED_PATH` with `findings`, keeping
    the author's `ACCEPTED` rows (a finding matching one isn't added again)
    except, with `prose`, those whose quote is no longer in it. The file
    goes when it has no rows."""
    rows = reported(project_dir)
    accepted = [r for r in rows.pop(scene_id, []) if r['command'] == ACCEPTED
                and (prose is None or _quoted_in(r['quote'], prose))]
    new = [r for r in _finding_rows(scene_id, command, findings)
           if not any(_same(r, a) for a in accepted)]
    if accepted or new:
        rows[scene_id] = accepted + new
    _write_rows(project_dir, REPORTED_PATH, rows)


def record_blocked(project_dir: str, scene_id: str, command: str,
                   findings: list[Finding]) -> None:
    """Replace `scene_id`'s rows in `BLOCKED_PATH` with `findings` (none:
    its rows go)."""
    rows = blocked(project_dir)
    rows.pop(scene_id, None)
    if findings:
        rows[scene_id] = _finding_rows(scene_id, command, findings)
    _write_rows(project_dir, BLOCKED_PATH, rows)


def _note_blocked(project_dir: str, scene_id: str, command: str, result: 'GateResult') -> str:
    """Record the verified contradictions that stopped `result`, for
    `storyforge check --accept`. A file that can't be read or written
    (malformed, or an OS error: SF-1, #504's review) is said, the gate's
    verdict unchanged, and returned ('' when written): its rows may then
    describe another run's prose, which `accept_blocked` refuses."""
    try:
        record_blocked(project_dir, scene_id, command,
                       [f for f in result.findings if f.kind == 'contradiction'])
    except (GateError, OSError) as e:
        from storyforge.common import log
        why = f'{BLOCKED_PATH} could not be updated: {e}'
        log(f'WARNING: {scene_id} did not pass, and {why}. Its contradictions can\'t be '
            f'accepted until a check records them.')
        return why
    return ''


def accept_blocked(project_dir: str, scene_id: str) -> list[dict[str, str]]:
    """The author accepts the verified contradictions that stopped
    `scene_id`'s last gate run (Ben, 2026-11-02): its `BLOCKED_PATH` rows
    move to `REPORTED_PATH` as `ACCEPTED`, so later gate runs of the scene
    report them, not stop on them, and a `RECHECK_FAILED` listing goes back
    to `RECHECK` (the author has acted). Returns the rows accepted (none:
    nothing is recorded for the scene, nothing changed).

    Raises:
        GateError: a file is malformed or can't be written."""
    stopped = blocked(project_dir)
    rows = stopped.pop(scene_id, [])
    if not rows:
        return []
    # SF-1 (#504's review): a run whose rows couldn't be replaced leaves
    # another prose's findings; accept only what the scene on disk says
    try:
        with open(os.path.join(project_dir, 'scenes', f'{scene_id}.md'),
                  encoding='utf-8') as f:
            prose = f.read()
    except (OSError, UnicodeDecodeError) as e:
        raise GateError(f'{scene_id}: can\'t read the scene to match its recorded '
                        f'contradictions: {e}') from e
    gone = [r['quote'] for r in rows if not _found_in(r['quote'], prose)]
    if gone:
        raise GateError(f'{scene_id}: {len(gone)} recorded contradiction(s) quote words not '
                        f'in the scene ("{gone[0][:80]}"): {BLOCKED_PATH} describes other '
                        f'prose; nothing accepted. Run `storyforge check {scene_id}` to '
                        f'record what this prose has.')
    kept = reported(project_dir)
    mine = kept.setdefault(scene_id, [])
    for r in rows:
        mine[:] = [m for m in mine if not _same(m, r)]
        mine.append({**r, 'command': ACCEPTED})
    _write_rows(project_dir, REPORTED_PATH, kept)
    _write_rows(project_dir, BLOCKED_PATH, stopped)
    row = pending(project_dir).get(scene_id)
    if row and row['command'] == RECHECK_FAILED:
        mark_pending(project_dir, scene_id, RECHECK,
                     f're-check: the author accepted {len(rows)} finding(s)')
    return rows


# ============================================================================
# The re-check (Phase 4, docs/plans/2026-10-31-phase4-safe-revision-design.md §3)
# ============================================================================

#: What one re-gated scene is forecast to cost: an extraction and a
#: persistence call (Sonnet) and `GATE_READINGS` checks (Opus, the story so
#: far cached). E4's one-reading gate ran about $0.35-0.45 a scene on
#: shared-dark, and a second reading about $0.35 more against a cold cache
#: (E8, 2026-11-01); rounded up.
RECHECK_COST_PER_SCENE = 0.6 + 0.35 * (GATE_READINGS - 1)


#: What `write`'s token-model forecast prices one drafted scene's gate at
#: (#556's review): a gate run (`RECHECK_COST_PER_SCENE`), plus a share for
#: the fixes, their re-gates and the partial-fix retry (`_partial_fix`), which
#: run only on the scenes that fail. A quarter more is an estimate, not
#: measured; the ledger-priced forecast (`costs.forecast_write`) counts
#: what this book's gates actually cost, retries included
WRITE_GATE_COST_PER_SCENE = RECHECK_COST_PER_SCENE * 1.25


#: A pending row's command for a scene listed for a re-check, and for one
#: whose re-check didn't pass (not re-run until the author acts:
#: `storyforge check --pending` or a redraft)
RECHECK, RECHECK_FAILED = 'recheck', 'recheck-failed'
#: A scene whose prose states a fact the author rejected: the author revises
#: it; when it passes the gate, the scenes depending on the rejection are
#: listed (its reason carries `[rejected: ids]`, kept by `mark_pending`)
REVISE_REJECTED = 'revise-rejected'


@dataclass
class Recheck:
    """`recheck_pending`'s answer."""
    passed: list[str] = field(default_factory=list)
    #: the scene that didn't pass, and why ('' when none failed)
    failed: str = ''
    why: str = ''
    result: GateResult | None = None
    #: the re-check scenes still pending when it stopped
    left: list[str] = field(default_factory=list)
    #: the forecast was over the cost threshold, so it stopped before a scene
    over_budget: bool = False
    forecast: float = 0.0
    #: `spent_before` plus this call's re-checks at their forecast: what the
    #: run has spent or reserved (`costs.RunBudget.committed`) once they ran
    spent: float = 0.0
    #: what the caller's run had spent and reserved before this call
    spent_before: float = 0.0


def recheck_queue(project_dir: str, skip: set[str] | frozenset[str] = frozenset()) -> list[str]:
    """The scenes pending a re-check (`RECHECK`, not `RECHECK_FAILED`), in
    reading order, without `skip`."""
    order = ledger.scene_order(project_dir)
    return sorted((s for s, r in pending(project_dir).items()
                   if r['command'] == RECHECK and s not in skip and s in order),
                  key=order.get)


def recheck_pending(project_dir: str, *, log_dir: str, skip: set[str] | frozenset[str] = frozenset(),
                    spent_before: float = 0.0, extract_model: str | None = None,
                    check_model: str | None = None) -> Recheck:
    """Re-gate the scenes pending a re-check (design §3), one at a time in
    reading order, never editing their prose: each one's commitments are
    extracted again against the ledger as it now is, checked, and committed
    when clean, which may list later scenes in turn (the cascade only moves
    forward: a scene lists only scenes after it). Stops at the first scene
    that doesn't pass, listed `RECHECK_FAILED` with the reason so it isn't
    re-run until the author acts (Ben, 2026-10-31: report and stop); the
    rest stay pending. `skip` is scenes the caller is about to redraft.

    Cost (Ben: forecast, and run under the threshold): the forecast is
    logged first; before each scene, `spent_before` plus this call's spend
    plus the queue left at `RECHECK_COST_PER_SCENE` must be within
    `costs.check_threshold`, otherwise it stops with `over_budget` and
    everything stays pending for `storyforge check --pending`. The
    threshold is one budget for the caller's whole run (`costs.RunBudget`):
    `spent_before` is what the run has spent so far, drafting and gating
    included, plus what it reserves for the work it still owes, so the
    re-checks get only what is left."""
    from storyforge.common import log
    from storyforge.costs import check_threshold, cost_threshold
    run = Recheck(spent=spent_before, spent_before=spent_before)
    announced = False
    while True:
        queue = recheck_queue(project_dir, skip)
        if not queue:
            return run
        run.forecast = run.spent + len(queue) * RECHECK_COST_PER_SCENE
        if not check_threshold(run.forecast):
            run.over_budget, run.left = True, queue
            log(f'WARNING: re-checking {len(queue)} scene(s) ({", ".join(queue[:8])}) would '
                f'bring this run to about ${run.forecast:.2f} (${run.spent_before:.2f} of it '
                f'spent or owed before the re-checks), over the cost threshold '
                f'(${cost_threshold():g}): not run. They stay in {PENDING_PATH}; run '
                f'`storyforge check --pending` (with STORYFORGE_COST_THRESHOLD raised if '
                f'needed).')
            return run
        if not announced:
            log(f'Re-checking {len(queue)} scene(s) whose facts depend on what changed, '
                f'forecast about ${len(queue) * RECHECK_COST_PER_SCENE:.2f}: {", ".join(queue)}')
            announced = True
        sid = queue[0]
        log(f'Re-checking {sid}...')
        run.spent += RECHECK_COST_PER_SCENE   # paid whether or not it finishes
        try:
            logs = run_log_dir(os.path.join(log_dir, 'recheck'), sid)
            log(f'  logs: {os.path.relpath(logs, project_dir)}')
            result = gate_scene(project_dir, sid, command='recheck', log_dir=logs,
                                extract_model=extract_model, check_model=check_model,
                                introduced_by=_writer(project_dir, sid))
        except GateError as e:
            why = ' '.join(str(e).split())
            mark_pending(project_dir, sid, RECHECK_FAILED, f're-check could not run: {why}')
            run.failed, run.why, run.left = sid, why, recheck_queue(project_dir, skip)
            return run
        if not result.passed:
            lines = blocking_lines(report_lines(result))
            mark_pending(project_dir, sid, RECHECK_FAILED,
                         f're-check did not pass: {len(lines)} problem(s): '
                         + '; '.join(_one_line(x) for x in lines[:3]))
            run.failed, run.why, run.result = sid, '; '.join(lines[:3]), result
            run.left = recheck_queue(project_dir, skip)
            return run
        run.passed.append(sid)


def _writer(project_dir: str, scene_id: str) -> str:
    """The command that wrote `scene_id`'s prose, as its commitments record
    it (the most common), so a re-check keeps it; `recheck` when none do."""
    from collections import Counter
    writers = Counter((r.get('introduced_by') or '').strip() for r in ledger.load(project_dir)
                      if ledger.is_commitment(r) and (r.get('scene_id') or '').strip() == scene_id)
    return writers.most_common(1)[0][0] if writers else 'recheck'
