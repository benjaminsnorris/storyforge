"""Deaths from the source (#745): characters.csv's `death_scene`, filled by
code in a faithful adaptation.

`continuity.check_life` binds a registry death to its character id at load
(#733), so a filled `death_scene` makes every presence of that id after the
death a finding with no model reading the death. Where the source records
a death (`source_deaths`), in the imported copy, so ids and names are the
book's (the import applies the name map):

- the source's own characters.csv `death_scene` (a source scene id). It
  wins over the ledger;
- the source's ledger, `commitments.csv`, read by two narrow patterns:
  a fact whose `subject` is the character and whose statement opens by
  saying they died (`VICTIM`: "Killed by Diomedes's spear...", "Struck dead
  by...", "Lies dead..."), and a fact with no subject that opens "<name>
  killed <name>" (`KILLED`: "Achilles killed Hector with a spear...", with
  "Deiphobus' spear killed..." allowed), whose victim binds one character
  by the one person rule (`continuity.Book.person`: a name several
  characters share, Homer's two Pisanders, binds none, and is a note).
  Only those openings count: "Menelaus kills Scamandrius" (subject
  Menelaus), "Nestor says many Achaeans have died" and "Ares killed
  Bellerophon's son" are not read as a death. A death the ledger states in
  several scenes is the earliest (a later one retells it).

The series cast (`series-bible/cast.csv`'s `last` scene) is not a death:
Hector's last scene is a harper's song in Quintus, Achilles' a shade in the
Odyssey, and most of the Iliad's people last seen in it (Chryses,
Bellerophon, an ancestor named once) never die there. So it isn't read.

`plan_deaths` places each death in the book through `reference/source-map.csv`
(the last active book scene adapting the source scene: a registry death
stands at the end of its scene, so a presence earlier in the death's own
scene is never put after it) and returns what to fill, only into a blank
cell of a character the registry has by that id (namesakes are distinct
ids, so the two Pisanders never collide). Everything it can't fill is said:
`problems` for the author (a death in a source scene the map cuts or leaves
out, deaths in two sources, a `death_scene` the author set that the source
places elsewhere, a source death_scene that isn't a source scene) and
`notes` for what wasn't read (no map, a source not imported, free mode,
deaths outside the range, of people the registry doesn't have, or by a
shared name). `storyforge cleanup` fills and reports (`cmd_cleanup`
`plan_death_scenes`, `_check_source_deaths`); the author's own values are
never overwritten.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Callable

from storyforge import source

#: A ledger statement that opens by saying its subject died.
VICTIM = re.compile(
    r"^(?:killed|slain|struck dead|shot dead|cut down|speared dead) by\b"
    r"|^(?:lies|lay|falls|fell|dropped|drops) dead\b", re.IGNORECASE)

_NAME = r"[A-Z][\w'’-]*(?: (?:son|daughter) of [A-Z][\w'’-]*)?"
#: A subject-less ledger statement that opens "<killer> killed <victim>".
KILLED = re.compile(
    r"^" + _NAME + r"(?:'s|’s|'|’)?(?: (?:spear|sword|arrow|stone|lance|shaft))?"
    r" (?:killed|slew|has killed|has slain) (?P<victim>" + _NAME + r")")

REGISTRY = 'characters.csv death_scene'


@dataclass(frozen=True)
class SourceDeath:
    """A death the source records: the book's character id, the source's
    slug and scene, and the evidence (`REGISTRY`, or a ledger fact's id and
    statement)."""
    who: str
    slug: str
    scene: str
    evidence: str

    @property
    def ref(self) -> str:
        return f'{self.slug}:{self.scene}'


@dataclass(frozen=True)
class DeathFill:
    """A blank `death_scene` to fill: `scene_id` is the last active book
    scene of `adapting`, the scenes adapting the source scene of `death`."""
    who: str
    scene_id: str
    death: SourceDeath
    adapting: tuple[str, ...]

    def describe(self) -> str:
        more = (f', the last of {len(self.adapting)} scenes adapting it'
                if len(self.adapting) > 1 else '')
        return (f'death_scene {self.scene_id} for {self.who} in reference/characters.csv '
                f'(the source kills them in {self.death.ref}{more})')


@dataclass(frozen=True)
class DeathPlan:
    fills: tuple[DeathFill, ...] = ()
    problems: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()


def _names(xs, n=5) -> str:
    xs = list(xs)
    return ', '.join(xs[:n]) + (f' and {len(xs) - n} more' if len(xs) > n else '')


def person_resolver(rows: list[dict[str, str]], path: str) -> Callable[[str], str | None]:
    """The id a name binds in the book's characters.csv, by #733's one
    person rule (`continuity.Book.person`), else None."""
    from storyforge import continuity
    from storyforge.enrich import load_alias_map
    book = continuity.Book('', {}, {}, chars=load_alias_map(path),
                           namesakes=continuity.namesakes(rows),
                           ids=continuity.registry_ids(rows))

    def person(name: str) -> str | None:
        cid = book.person(name)
        return str(cid) if cid else None
    return person


def source_deaths(project_dir: str, cfg: source.SourceConfig,
                  person: Callable[[str], str | None]
                  ) -> tuple[dict[str, list[SourceDeath]], list[str], list[str]]:
    """{book character id: the deaths the imported sources record, one per
    source} (module docstring), problems (a source death_scene that isn't a
    scene of its source) and notes (a source not imported or unreadable, a
    victim's name binding no one character). `person` binds a name to an
    id (`person_resolver`)."""
    out: dict[str, list[SourceDeath]] = {}
    problems: list[str] = []
    notes: list[str] = []
    unbound: set[str] = set()
    for slug in cfg.slugs():
        if not source.is_imported(project_dir, slug):
            notes.append(f'source {slug} is not imported, so its deaths weren\'t read '
                         f'(run `storyforge source import`)')
            continue
        try:
            order = {r['id'].strip(): n for n, r in
                     enumerate(source.source_scenes(project_dir, slug)) if r.get('id', '').strip()}
            chars = source.read_table(project_dir, slug, 'characters.csv')
            facts = source.read_table(project_dir, slug, 'commitments.csv')
        except source.SourceError as e:
            notes.append(f'{e}; its deaths weren\'t read')
            continue
        own: dict[str, SourceDeath] = {}
        for row in chars:
            who, scene = row.get('id', '').strip(), row.get('death_scene', '').strip()
            if not (who and scene):
                continue
            scene = scene.split(':', 1)[1] if scene.startswith(f'{slug}:') else scene
            if scene not in order:
                problems.append(f'source {slug}\'s characters.csv gives {who} death_scene '
                                f'{scene}, which is not a scene of the source; not filled')
                continue
            own[who] = SourceDeath(who, slug, scene, REGISTRY)
        stated: dict[str, SourceDeath] = {}
        for row in facts:
            scene = row.get('scene_id', '').strip()
            statement = ' '.join(row.get('statement', '').split())
            if scene not in order or row.get('status', '').strip() == 'superseded':
                continue
            subject = row.get('subject', '').strip()
            if subject:
                who = subject if ';' not in subject and VICTIM.match(statement) else None
            else:
                m = KILLED.match(statement)
                victim = m.group('victim') if m else ''
                if not victim or re.search(r"(?:'s|’s|'|’)$", victim):
                    continue   # someone's son, charioteer, comrade: not named here
                who = person(victim)
                if who is None:
                    unbound.add(victim)
            if not who:
                continue
            death = SourceDeath(who, slug, scene, f'commitments.csv {row.get("id", "").strip()}: '
                                                  f'{statement}')
            if who not in stated or order[scene] < order[stated[who].scene]:
                stated[who] = death
        for who in set(own) | set(stated):
            out.setdefault(who, []).append(own.get(who) or stated[who])
    if unbound:
        notes.append(f'{len(unbound)} name(s) the source ledger says were killed bind no one '
                     f'character in reference/characters.csv (a name several share, or none '
                     f'has), so their deaths aren\'t filled: {_names(sorted(unbound))}')
    return out, problems, notes


def _placements(rows: list[dict[str, str]], cat: dict, order: dict[str, int]
                ) -> tuple[dict[tuple[str, str], list[str]], set[tuple[str, str]]]:
    """{(slug, source scene): the active book scenes adapting it, in reading
    order} and the source scenes the map cuts."""
    adapted: dict[tuple[str, str], list[str]] = {}
    cut: set[tuple[str, str]] = set()
    for r in rows:
        for ref in source.split_ids(r.get('source_scenes', '')):
            hit = source.resolve_source_id(ref, cat)
            if hit is None:
                continue   # validate's coverage check reports it
            if r.get('treatment') == 'cut':
                cut.add(hit)
            elif r.get('scene_id') in order:
                adapted.setdefault(hit, []).append(r['scene_id'])
    for hit in adapted:
        adapted[hit] = sorted(set(adapted[hit]), key=order.get)
    return adapted, cut


def plan_deaths(project_dir: str) -> DeathPlan:
    """What to fill in characters.csv's `death_scene` from the source, and
    what couldn't be (module docstring). Empty for a project with no
    `source:` block."""
    from storyforge.elaborate import _read_csv
    try:
        cfg = source.read_config(project_dir)
    except source.SourceError as e:
        return DeathPlan(notes=(f'{e}; deaths not filled from the source',))
    if cfg is None:
        return DeathPlan()
    if cfg.mode != 'faithful':
        return DeathPlan(notes=(f'the adaptation is in {cfg.mode} mode, so deaths are not '
                                f'filled from the source',))
    path = os.path.join(project_dir, 'reference', 'characters.csv')
    chars = _read_csv(path)
    if not chars:
        return DeathPlan(notes=('reference/characters.csv has no rows, so no death is '
                                'filled from the source',))
    deaths, problems, notes = source_deaths(project_dir, cfg, person_resolver(chars, path))
    if not deaths:
        return DeathPlan(problems=tuple(problems), notes=tuple(notes))
    if 'death_scene' not in chars[0]:
        problems.append(f'reference/characters.csv has no death_scene column, so the '
                        f'{len(deaths)} death(s) the source records aren\'t filled; add the '
                        f'column (`storyforge cleanup --csv` reports it)')
        return DeathPlan(problems=tuple(problems), notes=tuple(notes))
    try:
        rows = source.read_source_map(project_dir)
        if rows is not None:
            cat = source.catalogue(project_dir, cfg)
            spans = {s: (None if not source.is_imported(project_dir, s)
                         else source.adapted_ids(project_dir, cfg, s)) for s in cfg.slugs()}
    except source.SourceError as e:
        notes.append(f'{e}; deaths not placed in the book')
        return DeathPlan(problems=tuple(problems), notes=tuple(notes))
    if rows is None:
        notes.append(f'no reference/{source.SOURCE_MAP} yet, so the {len(deaths)} death(s) '
                     f'the source records aren\'t placed in the book')
        return DeathPlan(problems=tuple(problems), notes=tuple(notes))
    order = {r['id']: n for n, r in enumerate(source.active_scenes(project_dir))}
    adapted, cut = _placements(rows, cat, order)

    have = {(r.get('id') or '').strip(): (r.get('death_scene') or '').strip()
            for r in chars if (r.get('id') or '').strip()}
    fills: list[DeathFill] = []
    outside, unknown = [], []
    for who in sorted(deaths):
        if who not in have:
            unknown.append(who)
            continue
        inside = [d for d in deaths[who]
                  if spans.get(d.slug) is None or d.scene in spans[d.slug]]
        if not inside:
            outside.append(who)
            continue
        if len(inside) > 1:
            problems.append(f'the sources record {who}\'s death in more than one '
                            f'({", ".join(d.ref for d in inside)}); death_scene not filled: '
                            f'set it yourself')
            continue
        death = inside[0]
        hit = (death.slug, death.scene)
        where = adapted.get(hit, [])
        own = have[who]
        if not where:
            if not own:
                how = 'cuts' if hit in cut else 'doesn\'t adapt'
                problems.append(f'the source kills {who} in {death.ref}, which the source '
                                f'map {how}, so the book has no scene for the death; set '
                                f'death_scene to the scene after which {who} is dead, or '
                                f'leave it blank if they live')
            continue
        if not own:
            fills.append(DeathFill(who, where[-1], death, tuple(where)))
        elif own not in where:
            problems.append(f'reference/characters.csv gives {who} death_scene {own}, but the '
                            f'source kills them in {death.ref}, which the book adapts in '
                            f'{_names(where)}; check which is meant')
    if outside:
        notes.append(f'{len(outside)} death(s) the source records fall outside the adapted '
                     f'range, so not filled: {_names(outside)}')
    if unknown:
        notes.append(f'{len(unknown)} death(s) the source records are of people '
                     f'reference/characters.csv has no row for: {_names(unknown)}')
    return DeathPlan(tuple(fills), tuple(problems), tuple(notes))


def apply_fills(project_dir: str, fills: tuple[DeathFill, ...]) -> list[DeathFill]:
    """Write each fill into its blank cell; returns the ones written (a row
    whose cell is no longer blank, or that is gone, is left as it is)."""
    from storyforge.csv_cli import update_field
    from storyforge.elaborate import _read_csv
    path = os.path.join(project_dir, 'reference', 'characters.csv')
    blank = {(r.get('id') or ''): not (r.get('death_scene') or '').strip()
             for r in _read_csv(path)}
    for f in fills:
        if blank.get(f.who):
            update_field(path, f.who, 'death_scene', f.scene_id)
    now = {(r.get('id') or ''): (r.get('death_scene') or '').strip() for r in _read_csv(path)}
    return [f for f in fills if blank.get(f.who) and now.get(f.who) == f.scene_id]
