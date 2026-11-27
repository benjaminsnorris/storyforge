"""Deaths from the source (#745): characters.csv's `death_scene`, filled by
code in a faithful adaptation.

`continuity.check_life` binds a registry death to its character id at load
(#733), so a filled `death_scene` makes every presence of that id after the
death a finding with no model reading the death. Where the source records
a death (`source_deaths`), in the imported copy, so ids and names are the
book's (the import applies the name map):

- the source's own characters.csv `death_scene` (a source scene id). It
  wins over the ledger; one naming no source scene is a finding, and the
  ledger isn't asked in its place;
- the source's ledger, `commitments.csv`, read by two narrow patterns:
  a fact whose `subject` is the character and whose statement opens by
  saying they died (`VICTIM`: "Killed by Diomedes's spear...", "Struck dead
  by...", "Lies dead where he fell..."), and a fact with no subject that
  opens "<name> killed <name>" (`KILLED`: "Achilles killed Hector with a
  spear...", with "Deiphobus' spear killed..." allowed), whose victim binds
  one character by the one person rule (`continuity.Book.person`: a name
  several characters share, Homer's two Pisanders, binds none). Only those
  openings count: "Menelaus kills Scamandrius" (subject Menelaus), "Nestor
  says Hector killed Leodes", "Killed by grief", "Falls dead drunk" and
  "Ares killed Bellerophon's son" are not read as a death. A death the
  ledger states in several scenes is the earliest (a later one retells it).

The series cast (`series-bible/cast.csv`'s `last` scene) is not a death:
Hector's last scene is a harper's song in Quintus, Achilles' a shade in the
Odyssey, and most of the Iliad's people last seen in it (Chryses,
Bellerophon, an ancestor named once) never die there. So it isn't read.

`plan_deaths` places each death in the book through `reference/source-map.csv`
(the last active book scene adapting the source scene: a registry death
stands at the end of its scene, so a presence earlier in the death's own
scene is never put after it) and fills only a blank cell of a character the
registry has by that id (namesakes are distinct ids, so the two Pisanders
never collide). A cell the author has set is theirs: a scene id, or
`typed_state.LIVES` (`lives`) for someone this version keeps alive.

Everything it doesn't fill or couldn't check is a `DeathFinding` for
cleanup's report (`cmd_cleanup._check_source_deaths`), so `cleanup --csv`
shows it: a `warning` the author can act on, which stops once they set
the cell (a death in a scene the map cuts or doesn't adapt, a fill a later
scene contradicts by putting the character on stage or as POV, deaths in
two sources, a source `death_scene` naming no scene, a source table that
can't be read or is missing, no usable map or range, an unreadable
registry), and `info` for what is the author's already or can't be pinned
to one character (an author's `death_scene` the source places elsewhere,
free mode, no map yet, deaths outside the range, of people the registry
doesn't have, by a shared name, or in a fact with several subjects).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Callable

from storyforge import source
from storyforge.typed_state import LIVES

#: A ledger statement that opens by saying its subject died: by someone or
#: something named ("by Diomedes's spear", "by the spear of"), or lying dead
#: somewhere (not "killed by grief", "falls dead drunk").
VICTIM = re.compile(
    r"^(?i:killed|slain|struck dead|shot dead|cut down|speared dead) by "
    r"(?:[A-Z]|(?i:a|an|the|his|her|their) )"
    r"|^(?i:lies|lay|falls|fell|dropped|drops) dead"
    r"(?=$|[.,;:]| (?:where|on|in|at|by|beside|before|from|with|among|across|under|upon|"
    r"and)\b)")

_NAME = r"[A-Z][\w'’-]*(?: (?:son|daughter) of [A-Z][\w'’-]*)?"
#: A subject-less ledger statement that opens "<killer> killed <victim>".
KILLED = re.compile(
    r"^" + _NAME + r"(?:'s|’s|'|’)?(?: (?:spear|sword|arrow|stone|lance|shaft))?"
    r" (?:killed|slew|has killed|has slain) (?P<victim>" + _NAME + r")")

REGISTRY = 'characters.csv death_scene'
WARNING, INFO = 'warning', 'info'


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
class DeathFinding:
    """What the plan didn't fill or couldn't check: `severity` `WARNING`
    (the author can act) or `INFO` (theirs already, or not one character)."""
    severity: str
    detail: str


@dataclass(frozen=True)
class DeathPlan:
    fills: tuple[DeathFill, ...] = ()
    findings: tuple[DeathFinding, ...] = ()

    def of(self, severity: str) -> list[str]:
        return [f.detail for f in self.findings if f.severity == severity]


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


class _Found:
    def __init__(self):
        self.items: list[DeathFinding] = []

    def warn(self, text: str) -> None:
        self.items.append(DeathFinding(WARNING, text))

    def info(self, text: str) -> None:
        self.items.append(DeathFinding(INFO, text))


def source_deaths(project_dir: str, cfg: source.SourceConfig,
                  person: Callable[[str], str | None], found: _Found | None = None
                  ) -> tuple[dict[str, list[SourceDeath]], set[str]]:
    """({book character id: the deaths the imported sources record, one per
    source}, the ids whose source registry death_scene names no scene, which
    are not filled from the ledger either). What couldn't be read goes to
    `found` (module docstring). `person` binds a name to an id
    (`person_resolver`)."""
    found = found if found is not None else _Found()
    out: dict[str, list[SourceDeath]] = {}
    bad: set[str] = set()
    unbound: set[str] = set()
    several: list[str] = []
    for slug in cfg.slugs():
        if not source.is_imported(project_dir, slug):
            found.warn(f'source {slug} is not imported, so the deaths it records weren\'t '
                       f'read or filled (run `storyforge source import`)')
            continue
        try:
            order = {r['id'].strip(): n for n, r in
                     enumerate(source.source_scenes(project_dir, slug)) if r.get('id', '').strip()}
            chars = source.read_table(project_dir, slug, 'characters.csv')
            facts = source.read_table(project_dir, slug, 'commitments.csv')
        except (source.SourceError, OSError, UnicodeDecodeError) as e:
            found.warn(f'{e}; the deaths source {slug} records weren\'t read or filled')
            continue
        for table in ('characters.csv', 'commitments.csv'):
            if not os.path.isfile(os.path.join(source.source_dir(project_dir, slug), table)):
                found.warn(f'reference/source/{slug}/{table} is missing, so the deaths it '
                           f'would record weren\'t read (re-run `storyforge source import`)')
        own: dict[str, SourceDeath] = {}
        for row in chars:
            who, scene = row.get('id', '').strip(), row.get('death_scene', '').strip()
            if not (who and scene) or scene.lower() == LIVES:
                continue
            scene = scene.split(':', 1)[1] if scene.startswith(f'{slug}:') else scene
            if scene not in order:
                found.warn(f'source {slug}\'s characters.csv gives {who} death_scene {scene}, '
                           f'which is not a scene of the source, so {who}\'s death isn\'t '
                           f'filled; fix the source, or set death_scene yourself')
                bad.add(who)
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
                if not VICTIM.match(statement):
                    continue
                if ';' in subject:
                    several.append(row.get('id', '').strip() or scene)
                    continue
                who = subject
            else:
                m = KILLED.match(statement)
                victim = m.group('victim') if m else ''
                if not victim or re.search(r"(?:'s|’s|'|’)$", victim):
                    continue   # someone's son, charioteer, comrade: not named here
                who = person(victim)
                if who is None:
                    unbound.add(victim)
                    continue
            death = SourceDeath(who, slug, scene, f'commitments.csv {row.get("id", "").strip()}: '
                                                  f'{statement}')
            if who not in stated or order[scene] < order[stated[who].scene]:
                stated[who] = death
        for who in (set(own) | set(stated)) - bad:
            out.setdefault(who, []).append(own.get(who) or stated[who])
    if unbound:
        found.info(f'{len(unbound)} name(s) the source ledger says were killed bind no one '
                   f'character in reference/characters.csv (a name several share, or none '
                   f'has), so those deaths aren\'t filled: {_names(sorted(unbound))}; set '
                   f'death_scene yourself for the one who dies')
    if several:
        found.info(f'{len(several)} source ledger death fact(s) name several subjects, so '
                   f'whose death isn\'t known and they aren\'t filled: {_names(several)}')
    return out, bad


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


def _present_after(project_dir: str, scenes: list[dict[str, str]],
                   person: Callable[[str], str | None]) -> dict[str, list[tuple[int, str]]]:
    """{character id: [(reading index, scene id)]} for each active scene in
    the present (not `elaborate.off_present`) that has them on stage
    (scene-intent.csv `on_stage`) or as its POV (scenes.csv `pov`)."""
    from storyforge.elaborate import _read_csv, off_present
    intent = {(r.get('id') or '').strip(): r for r in
              _read_csv(os.path.join(project_dir, 'reference', 'scene-intent.csv'))}
    out: dict[str, list[tuple[int, str]]] = {}
    for n, row in enumerate(scenes):
        if off_present(row):
            continue
        sid = row['id']
        tokens = source.split_ids((intent.get(sid) or {}).get('on_stage', ''))
        tokens.append((row.get('pov') or '').strip())
        for who in {person(t) for t in tokens if t}:
            if who:
                out.setdefault(who, []).append((n, sid))
    return out


def plan_deaths(project_dir: str) -> DeathPlan:
    """What to fill in characters.csv's `death_scene` from the source, and
    what wasn't filled or checked (module docstring). Empty for a project
    with no `source:` block."""
    from storyforge.elaborate import _read_csv
    found = _Found()

    def done(fills=()) -> DeathPlan:
        return DeathPlan(tuple(fills), tuple(found.items))
    try:
        cfg = source.read_config(project_dir)
    except source.SourceError as e:
        found.warn(f'{e}; deaths not filled from the source')
        return done()
    if cfg is None:
        return done()
    if cfg.mode != 'faithful':
        found.info(f'the adaptation is in {cfg.mode} mode, so deaths are not filled from '
                   f'the source')
        return done()
    path = os.path.join(project_dir, 'reference', 'characters.csv')
    try:
        chars = _read_csv(path)
    except (OSError, UnicodeDecodeError) as e:
        found.warn(f'reference/characters.csv could not be read ({type(e).__name__}), so '
                   f'no death is filled from the source')
        return done()
    if not chars:
        found.info('reference/characters.csv has no rows, so no death is filled from the '
                   'source')
        return done()
    person = person_resolver(chars, path)
    deaths, _bad = source_deaths(project_dir, cfg, person, found)
    if not deaths:
        return done()
    if 'death_scene' not in chars[0]:
        found.warn(f'reference/characters.csv has no death_scene column, so the '
                   f'{len(deaths)} death(s) the source records aren\'t filled; add the column')
        return done()
    try:
        rows = source.read_source_map(project_dir)
        if rows is not None:
            cat = source.catalogue(project_dir, cfg)
            spans = {s: (None if not source.is_imported(project_dir, s)
                         else source.adapted_ids(project_dir, cfg, s)) for s in cfg.slugs()}
            scenes = source.active_scenes(project_dir)
            present = _present_after(project_dir, scenes, person)
    except (source.SourceError, OSError, UnicodeDecodeError) as e:
        found.warn(f'{e}; the {len(deaths)} death(s) the source records aren\'t placed in '
                   f'the book')
        return done()
    if rows is None:
        found.info(f'no reference/{source.SOURCE_MAP} yet, so the {len(deaths)} death(s) '
                   f'the source records aren\'t placed in the book')
        return done()
    order = {r['id']: n for n, r in enumerate(scenes)}
    adapted, cut = _placements(rows, cat, order)

    have = {(r.get('id') or '').strip(): (r.get('death_scene') or '').strip()
            for r in chars if (r.get('id') or '').strip()}
    fills: list[DeathFill] = []
    outside, unknown = [], []
    for who in sorted(deaths):
        if who not in have:
            unknown.append(who)
            continue
        own = have[who]
        inside = [d for d in deaths[who]
                  if spans.get(d.slug) is None or d.scene in spans[d.slug]]
        if not inside:
            outside.append(who)
            continue
        if len(inside) > 1:
            if not own:
                found.warn(f'the sources record {who}\'s death in more than one '
                           f'({", ".join(d.ref for d in inside)}), so death_scene isn\'t '
                           f'filled: set it yourself (`{LIVES}` if they live)')
            continue
        death = inside[0]
        hit = (death.slug, death.scene)
        where = adapted.get(hit, [])
        if own.lower() == LIVES:
            continue   # the author keeps them alive
        if not where:
            if not own:
                how = 'cuts' if hit in cut else 'doesn\'t adapt'
                found.warn(f'the source kills {who} in {death.ref}, which the source map '
                           f'{how}, so the book has no scene for the death; set death_scene '
                           f'to the scene after which {who} is dead, or `{LIVES}` if they live')
            continue
        if own:
            if own not in where:
                found.info(f'reference/characters.csv gives {who} death_scene {own}, but the '
                           f'source kills them in {death.ref}, which the book adapts in '
                           f'{_names(where)}: kept as the author set it')
            continue
        later = [sid for n, sid in present.get(who, []) if n > order[where[-1]]]
        if later:
            found.warn(f'the source kills {who} in {death.ref} (the book\'s {where[-1]}), but '
                       f'later scene(s) {_names(later)} put {who} on stage or as POV, so '
                       f'death_scene isn\'t filled: set it to where {who} dies in this book, '
                       f'or `{LIVES}`')
            continue
        fills.append(DeathFill(who, where[-1], death, tuple(where)))
    if outside:
        found.info(f'{len(outside)} death(s) the source records fall outside the adapted '
                   f'range, so not filled: {_names(outside)}')
    if unknown:
        found.info(f'{len(unknown)} death(s) the source records are of people '
                   f'reference/characters.csv has no row for: {_names(unknown)}')
    return done(fills)


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
