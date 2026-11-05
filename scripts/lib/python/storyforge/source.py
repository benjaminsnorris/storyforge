"""Adaptation: a project built on a source project (#477).

A project whose `storyforge.yaml` has a `source:` block adapts another
Storyforge project (an extracted book, an earlier draft): a retelling, an
expansion, a rewrite. This module holds everything deterministic about that:

- `read_config`: the `source:` block (`SourceConfig`), or None without one.
- `load_name_map` / `NameMap`: the retelling's names
  (`source_id|target_id|source_name|target_name`). Registry ids and the
  `_ID_COLUMNS` are mapped by id (a token that is a name, in a project that
  keeps names there, by name), and a registry row's `name` comes from its
  `target_name`; every other cell, aliases included, gets whole-word,
  case-sensitive name replacement, longest name first. A row with an empty
  `source_id` is a text-only form (Ilius -> Ilium, "son of Saturn").
- `import_source`: copies a source project's scene CSVs, registries, ledger,
  structural CSVs and bibles into `reference/source/<slug>/` with the map
  applied (and `chapter-map.csv` for a chapters range), copies its prose
  (`scenes/*.md`) byte for byte, and writes
  `source-bible.md`. It writes nothing outside `reference/source/` (the new
  copy is staged in a sibling directory, then swapped in).
- `read_source_map` / `check_coverage`: `reference/source-map.csv`, which the
  map stage writes, and validate's coverage check of it.
- `SourceRange` / `resolve_range` / `adapted_ids` / `spans`: a source's
  optional `range:` (the chapters or scenes this novel adapts; the rest stays
  imported as context), and `check_bible_span`, which stops a bible built for
  another range.

A project with no `source:` block gets None from `read_config`, and every
caller does exactly what it did before.

The source's ledger is never merged into the project's own: it is read-only
context (`reference/source/<slug>/commitments.csv`).
"""

from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass, field

from storyforge.common import (
    csv_safe, is_unfilled_template, parse_yaml_scalar,
)
from storyforge.narrator import NARRATOR_POV, is_narrator

MODES = ('faithful', 'free')
DEFAULT_MODE = 'faithful'

TREATMENTS = ('dramatize', 'compress', 'expand', 'pov-shift', 'reorder',
              'invent', 'cut')

SOURCE_MAP = 'source-map.csv'
SOURCE_MAP_COLUMNS = ['scene_id', 'source_scenes', 'treatment', 'note']

NAME_MAP_COLUMNS = ['source_id', 'target_id', 'source_name', 'target_name']

SOURCE_BIBLE = 'source-bible.md'
CHAPTER_MAP = 'chapter-map.csv'

# What the import copies from the source's reference/ (when present).
IMPORTED_CSVS = (
    'scenes.csv', 'scene-intent.csv', 'scene-briefs.csv', 'characters.csv',
    'locations.csv', 'values.csv', 'mice-threads.csv', 'commitments.csv',
    'spine.csv', 'architecture.csv',
)
# The source's descriptive docs (extract phase 5, #440): copied with the map
# applied, for the author; only source-bible.md reaches the prompts.
IMPORTED_DOCS = (
    'story-summary.md', 'story-architecture.md', 'character-bible.md',
    'world-bible.md', 'systems-bible.md', 'timeline.md',
)

# Columns holding registry ids (characters and locations), mapped by id.
# Every other column gets name replacement, which is case-sensitive, so the
# lowercase ids in the remaining id columns are left alone as long as every
# source_name has a capital (load_name_map refuses one that doesn't).
_ID_COLUMNS = frozenset({'pov', 'location', 'characters', 'on_stage',
                         'subject', 'known_by'})
_REGISTRIES = ('characters.csv', 'locations.csv')


class SourceError(Exception):
    """A `source:` block, name map or source project that can't be used."""


# ============================================================================
# The `source:` block
# ============================================================================

RANGE_KINDS = ('chapters', 'scenes')


@dataclass(frozen=True)
class SourceRange:
    """The part of a source the novel adapts (a projects entry's `range:`):
    `chapters 1-4` (the `chapter` numbers of the source's chapter-map.csv) or
    `scenes first-id..last-id` (both ends included, in reading order). Seq
    numbers are not accepted: they are positions, and change when the source
    gains or loses a scene. Scene ids are permanent, and chapter numbers are
    fixed by the source's chapter map.

    The type holds its canonical form (chapter numbers without leading
    zeros; scene ends that are slugs), so `describe()` is an identity:
    `check_bible_span` compares it with the range the bible was built for,
    and `parse_range(describe())` gives the same range back."""
    kind: str
    first: str
    last: str

    def __post_init__(self):
        if self.kind not in RANGE_KINDS:
            raise SourceError(f'range kind {self.kind!r}; use one of {", ".join(RANGE_KINDS)}')
        if not (isinstance(self.first, str) and isinstance(self.last, str)):
            raise SourceError('a range\'s ends are text')
        if not self.first or not self.last:
            raise SourceError('a range needs both ends')
        if self.kind == 'chapters':
            if not (_ASCII_DIGITS.match(self.first) and _ASCII_DIGITS.match(self.last)):
                raise SourceError(f'chapter numbers must be whole numbers, not '
                                  f'{self.first!r} and {self.last!r}')
            object.__setattr__(self, 'first', str(int(self.first)))
            object.__setattr__(self, 'last', str(int(self.last)))
            if int(self.first) > int(self.last):
                raise SourceError(f'chapters {self.first}-{self.last} is inverted '
                                  f'(the first chapter comes after the last)')
        else:
            bad = [e for e in (self.first, self.last) if not _SLUG_RE.match(e)]
            if bad:
                raise SourceError(f'{bad[0]!r} is not a scene id (lowercase letters, digits '
                                  f'and hyphens); a range of scenes is `first-id..last-id`')

    def describe(self) -> str:
        """The range as written in storyforge.yaml (normalized)."""
        if self.kind == 'chapters':
            return (f'chapter {self.first}' if self.first == self.last
                    else f'chapters {self.first}-{self.last}')
        return (f'scene {self.first}' if self.first == self.last
                else f'scenes {self.first}..{self.last}')


_ASCII_DIGITS = re.compile(r'^[0-9]+$')
_CHAPTERS_RE = re.compile(r'^chapters?\s+([0-9]+)(?:\s*-\s*([0-9]+))?$')
_SCENES_RE = re.compile(r'^scenes?\s+(\S+?)(?:\s*\.\.\s*(\S+))?$')


def parse_range(slug: str, text: str) -> SourceRange:
    """A `range:` value: `chapters N-M` (or `chapter N`), or `scenes a..b` (or
    `scene a`). Raises SourceError for anything else, an inverted chapter
    range included; ids and chapters are checked against the source by
    `resolve_range`."""
    where = f'storyforge.yaml: source {slug} range {text!r}'
    t = text.strip()
    m = _CHAPTERS_RE.match(t) or _SCENES_RE.match(t)
    if not m:
        raise SourceError(f'{where}: write `chapters 1-4` (chapter numbers from the '
                          f'source\'s chapter-map.csv) or `scenes first-id..last-id`')
    first, last = m.group(1), m.group(2) or m.group(1)
    try:
        return SourceRange('chapters' if t.startswith('chapter') else 'scenes', first, last)
    except SourceError as e:
        raise SourceError(f'{where}: {e}') from e


@dataclass(frozen=True)
class SourceProject:
    slug: str
    path: str            # as written: relative to the project, or absolute
    name_map: str = ''   # a per-source override of SourceConfig.name_map
    range: SourceRange | None = None   # the part adapted; None: the whole source


@dataclass(frozen=True)
class SourceConfig:
    projects: tuple[SourceProject, ...]
    name_map: str = ''
    mode: str = DEFAULT_MODE
    rules: str = ''

    def slugs(self) -> list[str]:
        return [p.slug for p in self.projects]

    def project(self, slug: str) -> SourceProject:
        for p in self.projects:
            if p.slug == slug:
                return p
        raise SourceError(f'no source project with slug {slug!r} '
                          f'(storyforge.yaml lists: {", ".join(self.slugs())})')

    def __post_init__(self):
        if self.mode not in MODES:
            raise SourceError(f'storyforge.yaml: source.mode is {self.mode!r}; '
                              f'use one of {", ".join(MODES)}')
        if not self.projects:
            raise SourceError('storyforge.yaml: the `source:` block lists no '
                              '`projects` (each `- slug: ...` with a `path: ...`)')
        slugs = [p.slug for p in self.projects]
        for slug in slugs:
            if not _SLUG_RE.match(slug):
                raise SourceError(f'storyforge.yaml: source slug {slug!r} must be '
                                  f'lowercase letters, digits and hyphens')
            if slugs.count(slug) > 1:
                raise SourceError(f'storyforge.yaml: source slug {slug!r} is listed twice')

    def map_path(self, project: SourceProject) -> str:
        return project.name_map or self.name_map

    @property
    def gap_severity(self) -> str:
        """The severity of a coverage gap (a source scene unaccounted for, or
        cut with no reason) under this mode."""
        return {'faithful': 'blocking', 'free': 'advisory'}[self.mode]


_SLUG_RE = re.compile(r'^[a-z0-9][a-z0-9-]*$')


def _source_block(project_dir: str) -> list[str] | None:
    """The lines under a top-level `source:` key, or None without one."""
    path = os.path.join(project_dir, 'storyforge.yaml')
    try:
        with open(path, encoding='utf-8') as f:
            lines = f.read().splitlines()
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError) as e:
        raise SourceError(f'storyforge.yaml could not be read: {e}') from e
    for i, line in enumerate(lines):
        if re.match(r'^source:\s*(#.*)?$', line):
            block = []
            for nxt in lines[i + 1:]:
                if nxt.strip() and not nxt[0].isspace() and not nxt.lstrip().startswith('#'):
                    break
                block.append(nxt)
            return block
        if re.match(r'^source:\s*\S', line):
            raise SourceError('storyforge.yaml: `source:` must be a block '
                              '(projects, name_map, mode, rules), not a value')
    return None


def _parse_projects(block: list[str]) -> list[dict[str, str]]:
    """The `projects:` list of mappings inside the source block."""
    items: list[dict[str, str]] = []
    in_projects = False
    projects_indent = 0
    for line in block:
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        indent = len(line) - len(line.lstrip())
        m = re.match(r'^(\s+)projects:\s*(#.*)?$', line)
        if m:
            in_projects = True
            projects_indent = len(m.group(1))
            continue
        if not in_projects:
            continue
        if indent <= projects_indent and not line.lstrip().startswith('-'):
            in_projects = False
            continue
        item = re.match(r'^\s*-\s*(\w+):\s*(.*)$', line)
        if item:
            items.append({item.group(1): parse_yaml_scalar(item.group(2))})
            continue
        kv = re.match(r'^\s+(\w+):\s*(.*)$', line)
        if kv and items:
            if kv.group(1) in items[-1]:
                raise SourceError(f'storyforge.yaml: source project {len(items)} gives '
                                  f'`{kv.group(1)}` twice')
            items[-1][kv.group(1)] = parse_yaml_scalar(kv.group(2))
        elif kv:
            raise SourceError('storyforge.yaml: `source.projects` entries start '
                              'with `- slug: ...`')
        else:
            # Not `key: value` (e.g. `range : x`): never silently dropped
            raise SourceError(f'storyforge.yaml: can\'t read {line.strip()!r} in '
                              f'`source.projects` (write `key: value`)')
    return items


# The keys a `source.projects` entry and the `source:` block take; any other
# is refused, so a misspelled or misplaced `range:` can't silently mean the
# whole source
PROJECT_KEYS = ('slug', 'path', 'name_map', 'range')
BLOCK_KEYS = ('projects', 'name_map', 'mode', 'rules')


def _unknown_key(where: str, key: str, allowed: tuple[str, ...]) -> SourceError:
    hint = (' (a range goes on its project entry: `range: chapters 1-4`)'
            if key in ('range', 'ranges', 'chapters', 'chapter', 'scenes', 'from', 'to')
            else '')
    return SourceError(f'storyforge.yaml: {where} has no key `{key}`; it takes '
                       f'{", ".join(allowed)}{hint}')


def read_config(project_dir: str) -> SourceConfig | None:
    """The project's `source:` block, or None when it has none.

    Raises SourceError for a block that can't be used: no projects, a project
    without a slug or path, a repeated or malformed slug, an unknown mode, a
    key either level doesn't take (or a project gives twice), or a `range:`
    that is empty, malformed, or an inverted chapter range (an inverted
    scenes range needs the source: `resolve_range`).
    `mode` defaults to faithful; `name_map` and `rules` to nothing.
    """
    block = _source_block(project_dir)
    if block is None:
        return None
    projects = []
    for n, item in enumerate(_parse_projects(block), 1):
        slug = item.get('slug', '').strip()
        path = item.get('path', '').strip()
        if not slug or not path:
            raise SourceError(f'storyforge.yaml: source project {n} needs both '
                              f'`slug` and `path`')
        rng = None
        if 'range' in item:
            if not item['range'].strip():
                raise SourceError(f'storyforge.yaml: source {slug} has an empty `range:`; '
                                  f'write `range: chapters 1-4` or `range: scenes '
                                  f'first-id..last-id` on one line, or remove it')
            rng = parse_range(slug, item['range'])
        for key in item:
            if key not in PROJECT_KEYS:
                raise _unknown_key(f'source project {slug}', key, PROJECT_KEYS)
        projects.append(SourceProject(slug, path, item.get('name_map', '').strip(), rng))
    keys = _direct_keys(block)
    for key in keys:
        if key not in BLOCK_KEYS:
            raise _unknown_key('the `source:` block', key, BLOCK_KEYS)
    # SourceConfig checks the projects, the slugs and the mode
    return SourceConfig(
        projects=tuple(projects),
        name_map=keys.get('name_map', ''),
        mode=keys.get('mode') or DEFAULT_MODE,
        rules=keys.get('rules', ''),
    )


def _direct_keys(block: list[str]) -> dict[str, str]:
    """The block's own scalar keys (mode, name_map, rules), at its first
    line's indentation. `common.read_yaml_field('source.name_map')` would also
    match a project's own `name_map` inside the `projects` list."""
    content = [l for l in block if l.strip() and not l.lstrip().startswith('#')]
    if not content:
        return {}
    indent = len(content[0]) - len(content[0].lstrip())
    keys = {}
    for line in content:
        if len(line) - len(line.lstrip()) != indent or line.lstrip().startswith('-'):
            continue   # deeper, or a projects item written at the block's indent
        m = re.match(r'^\s+(\w+):\s*(.*)$', line)
        if not m:
            raise SourceError(f'storyforge.yaml: can\'t read {line.strip()!r} in the '
                              f'`source:` block (write `key: value`)')
        if m.group(1) in keys:
            raise SourceError(f'storyforge.yaml: the `source:` block gives '
                              f'`{m.group(1)}` twice')
        keys[m.group(1)] = parse_yaml_scalar(m.group(2))
    return keys


def resolve(project_dir: str, path: str) -> str:
    """A path from the source block, relative to the project."""
    return os.path.normpath(os.path.join(project_dir, os.path.expanduser(path)))


def source_dir(project_dir: str, slug: str) -> str:
    return os.path.join(project_dir, 'reference', 'source', slug)


def read_rules(project_dir: str, cfg: SourceConfig) -> str:
    """The text `source.rules` names: a file, or one section of it
    (`file.md#heading-slug`). '' when unset. Raises SourceError when it names
    something that isn't there, so a version rule is never silently dropped."""
    if not cfg.rules:
        return ''
    rel, _, anchor = cfg.rules.partition('#')
    path = resolve(project_dir, rel)
    try:
        with open(path, encoding='utf-8') as f:
            text = f.read()
    except (OSError, UnicodeDecodeError) as e:
        raise SourceError(f'source.rules: {rel} could not be read ({e})') from e
    if is_unfilled_template(path):
        raise SourceError(f'source.rules: {rel} is still its template; '
                          f'write the version rules there first')
    if not anchor:
        return text.strip()
    lines = text.splitlines()
    for i, line in enumerate(lines):
        m = re.match(r'^(#+)\s+(.*?)\s*$', line)
        if m and _heading_slug(m.group(2)) == anchor:
            level = len(m.group(1))
            out = [line]
            for nxt in lines[i + 1:]:
                h = re.match(r'^(#+)\s', nxt)
                if h and len(h.group(1)) <= level:
                    break
                out.append(nxt)
            return '\n'.join(out).strip()
    raise SourceError(f'source.rules: {rel} has no heading matching #{anchor}')


def _heading_slug(heading: str) -> str:
    slug = re.sub(r'[^\w\s-]', '', heading.lower())
    return re.sub(r'[\s]+', '-', slug.strip())


# ============================================================================
# The name map
# ============================================================================

@dataclass(frozen=True)
class NameMap:
    """A loaded name map. Frozen, and its pattern is built once here, so it
    can never disagree with `replacements`; `load_name_map` builds the dicts
    and constructs it once."""
    ids: dict[str, str] = field(default_factory=dict)            # source_id -> target_id
    id_names: dict[str, str] = field(default_factory=dict)       # source_id -> target_name
    replacements: dict[str, str] = field(default_factory=dict)   # source_name -> target_name
    ambiguous: dict[str, list[str]] = field(default_factory=dict)  # name -> its targets
    path: str = ''

    def __post_init__(self):
        changed = sorted(((s, t) for s, t in self.replacements.items() if s != t),
                         key=lambda p: (-len(p[0]), p[0]))
        object.__setattr__(self, '_changed', tuple(changed))
        object.__setattr__(self, '_lookup', dict(changed))
        pattern = None
        if changed:
            alternation = '|'.join(re.escape(s) for s, _ in changed)
            pattern = re.compile(rf'(?<!\w)(?:{alternation})(?!\w)')
        object.__setattr__(self, '_pattern', pattern)

    def changed(self) -> list[tuple[str, str]]:
        """The names the map changes, longest first."""
        return list(self._changed)

    def apply_text(self, text: str) -> str:
        """Replace each source name with its target name: whole words,
        case-sensitive, longest first (one pass, so a replacement is never
        replaced again)."""
        if self._pattern is None or not text:
            return text
        return self._pattern.sub(lambda m: self._lookup[m.group(0)], text)

    def map_token(self, token: str) -> str | None:
        """An id-column token's new value: by id, else (a project that keeps
        names in these columns) by name; None when the map knows neither."""
        if token in self.ids:
            return self.ids[token]
        if token in self.replacements:
            return self.replacements[token]
        return None

    def map_ids(self, cell: str, unknown: set[str] | None = None) -> str:
        """Map each `;`-separated token in an id cell; a token the map lacks
        stays, and is added to `unknown` when given."""
        if not cell:
            return cell
        out = []
        for tok in cell.split(';'):
            t = tok.strip()
            if not t:
                out.append(tok)
                continue
            mapped = self.map_token(t)
            if mapped is None:
                if unknown is not None:
                    unknown.add(t)
                mapped = t
            out.append(mapped)
        return ';'.join(out)


EMPTY_MAP = NameMap()


def load_name_map(path: str) -> NameMap:
    """Read a name map. Raises SourceError for a header that isn't exactly
    `NAME_MAP_COLUMNS`, a row with the wrong cell count, a registry row
    without a target id or name, a source id given two targets, a text-only
    row (empty `source_id`) without both names, or a source name with no
    capital letter (it could match an id inside text).

    A source name given two different target names (two people who share a
    name in the source but not in the retelling) can't be replaced in text;
    it is left as written and listed in `.ambiguous` for the caller to report.
    """
    try:
        with open(path, encoding='utf-8-sig', newline='') as f:
            lines = f.read().replace('\r\n', '\n').split('\n')
    except (OSError, UnicodeDecodeError) as e:
        raise SourceError(f'name map {path} could not be read ({e})') from e
    lines = [l for l in lines if l.strip()]
    if not lines or lines[0].split('|') != NAME_MAP_COLUMNS:
        raise SourceError(f'name map {path}: the header must be '
                          f'{"|".join(NAME_MAP_COLUMNS)}')
    ids: dict[str, str] = {}
    id_names: dict[str, str] = {}
    targets_of: dict[str, set[str]] = {}
    for n, line in enumerate(lines[1:], 2):
        cells = line.split('|')
        if len(cells) != len(NAME_MAP_COLUMNS):
            raise SourceError(f'name map {path} line {n}: {len(cells)} cells, '
                              f'expected {len(NAME_MAP_COLUMNS)}')
        sid, tid, sname, tname = (c.strip() for c in cells)
        if sid:
            if not tid or not tname:
                raise SourceError(f'name map {path} line {n}: {sid} needs a '
                                  f'target_id and a target_name')
            if sid in ids and ids[sid] != tid:
                raise SourceError(f'name map {path} line {n}: {sid} maps to both '
                                  f'{ids[sid]} and {tid}')
            ids[sid] = tid
            id_names[sid] = tname
        elif not sname or not tname:
            raise SourceError(f'name map {path} line {n}: a text-only row (no '
                              f'source_id) needs a source_name and a target_name')
        if sname:
            if sname == sname.lower():
                raise SourceError(f'name map {path} line {n}: source_name {sname!r} '
                                  f'has no capital letter')
            targets_of.setdefault(sname, set()).add(tname)
    replacements = {s: next(iter(t)) for s, t in targets_of.items() if len(t) == 1}
    ambiguous = {s: sorted(t) for s, t in targets_of.items() if len(t) > 1}
    return NameMap(ids, id_names, replacements, ambiguous, path)


# ============================================================================
# Import
# ============================================================================

@dataclass
class ImportResult:
    slug: str
    source_path: str
    dest: str
    files: dict[str, bytes] = field(default_factory=dict)   # relative to dest -> content
    missing: list[str] = field(default_factory=list)     # source files not there
    prose_files: int = 0
    notes: list[str] = field(default_factory=list)       # things the author should know
    changed: bool = False                                # anything differs on disk


def _read_rows(path: str) -> tuple[list[str], list[list[str]], str]:
    """Header, rows (as cell lists) and a problem ('' when none) of a
    pipe-delimited CSV, without quoting rules (the project's CSVs have none)."""
    with open(path, encoding='utf-8-sig', newline='') as f:
        text = f.read().replace('\r\n', '\n').replace('\r', '\n')
    lines = [l for l in text.split('\n') if l.strip()]
    if not lines:
        return [], [], 'empty'
    header = lines[0].split('|')
    rows = [l.split('|') for l in lines[1:]]
    bad = [n for n, r in enumerate(rows, 2) if len(r) != len(header)]
    problem = (f'{len(bad)} row(s) with the wrong number of cells (line {bad[0]})'
               if bad else '')
    return header, rows, problem


def _read_source_csv(slug: str, path: str, label: str) -> tuple[list[str], list[list[str]]]:
    """A source CSV, or SourceError naming it when it can't be read or is malformed."""
    try:
        header, rows, problem = _read_rows(path)
    except (OSError, UnicodeDecodeError) as e:
        raise SourceError(f'source {slug}: {label} could not be read ({e})') from e
    if problem and problem != 'empty':
        raise SourceError(f'source {slug}: {label}: {problem}')
    return header, rows


def _map_csv(name: str, header: list[str], rows: list[list[str]],
             nm: NameMap, unknown: dict[str, set[str]]) -> list[list[str]]:
    out = []
    id_idx = header.index('id') if 'id' in header else None
    name_idx = header.index('name') if 'name' in header else None
    for row in rows:
        new = []
        source_id = row[id_idx].strip() if id_idx is not None else ''
        for col, cell in zip(header, row):
            if col == 'pov' and is_narrator(cell):
                # The reserved narrator POV, which no name map lists (#555)
                new.append(NARRATOR_POV)
            elif (name in _REGISTRIES and col == 'id') or col in _ID_COLUMNS:
                new.append(nm.map_ids(cell, unknown.setdefault(f'{name}:{col}', set())))
            else:
                new.append(nm.apply_text(cell))
        if (name in _REGISTRIES and name_idx is not None
                and source_id in nm.id_names):
            # By id, so two people sharing a source name each get their own
            new[name_idx] = nm.id_names[source_id]
        out.append(new)
    return out


def _render_csv(header: list[str], rows: list[list[str]]) -> str:
    return '\n'.join('|'.join(r) for r in [header] + rows) + '\n'


def map_gaps(slug: str, src_ref: str, nm: NameMap) -> list[str]:
    """Registry ids (characters, locations) the map has no row for. Every
    registry entry needs one, even an unchanged name: a missing row is a gap,
    not a pass-through. Raises SourceError for a registry that can't be read
    or has no `id` column."""
    gaps = []
    for reg in _REGISTRIES:
        path = os.path.join(src_ref, reg)
        if not os.path.isfile(path):
            continue
        header, rows = _read_source_csv(slug, path, f'reference/{reg}')
        if 'id' not in header:
            raise SourceError(f'source {slug}: reference/{reg} has no id column')
        i = header.index('id')
        gaps += [f'{reg}:{r[i]}' for r in rows if r[i].strip() and r[i].strip() not in nm.ids]
    return gaps


def _inside(path: str, directory: str) -> bool:
    path, directory = os.path.realpath(path), os.path.realpath(directory)
    return path == directory or path.startswith(directory + os.sep)


def import_source(project_dir: str, cfg: SourceConfig, slug: str,
                  dry_run: bool = False) -> ImportResult:
    """Build one source's copy for `reference/source/<slug>/` and, unless
    `dry_run`, swap it in (`write_import`). Raises SourceError, before
    anything is written, when the source isn't a Storyforge project, a file
    it should copy is unreadable or malformed, the name map can't be used or
    lacks a registry entry, the map or rules file lives inside the
    directory the import replaces, or the project's `range:` for it can't be
    resolved (`resolve_range`). A chapters range also copies the source's
    chapter-map.csv; without a range nothing past `IMPORTED_CSVS` and
    `IMPORTED_DOCS` is copied, and the bible has no span line."""
    result = plan_import(project_dir, cfg, slug)
    if not dry_run:
        write_import(result)
    return result


def plan_import(project_dir: str, cfg: SourceConfig, slug: str) -> ImportResult:
    """Everything `import_source` would write, in memory; nothing is written."""
    proj = cfg.project(slug)
    src = resolve(project_dir, proj.path)
    src_ref = os.path.join(src, 'reference')
    dest = source_dir(project_dir, slug)
    if os.path.realpath(src) == os.path.realpath(project_dir):
        raise SourceError(f'source {slug}: the path is this project itself')
    if not os.path.isfile(os.path.join(src_ref, 'scenes.csv')):
        raise SourceError(f'source {slug}: {src} has no reference/scenes.csv; '
                          f'is it a Storyforge project?')
    # The import replaces dest wholesale: an author's file there would be deleted
    for label, rel in (('name map', cfg.map_path(proj)),
                       ('rules', cfg.rules.partition('#')[0])):
        if rel and _inside(resolve(project_dir, rel), dest):
            raise SourceError(f'source {slug}: the {label} {rel} is inside '
                              f'reference/source/{slug}/, which every import replaces; '
                              f'keep it elsewhere (e.g. reference/source/name-map.csv)')

    map_rel = cfg.map_path(proj)
    nm = EMPTY_MAP
    if map_rel:
        map_path = resolve(project_dir, map_rel)
        if not os.path.isfile(map_path):
            raise SourceError(f'source {slug}: name map {map_rel} not found')
        nm = load_name_map(map_path)
        gaps = map_gaps(slug, src_ref, nm)
        if gaps:
            shown = ', '.join(gaps[:12]) + (f' and {len(gaps) - 12} more'
                                            if len(gaps) > 12 else '')
            raise SourceError(f'source {slug}: the name map has no row for '
                              f'{len(gaps)} registry entr{"y" if len(gaps) == 1 else "ies"} '
                              f'({shown}); add a row for each, even an unchanged name')

    result = ImportResult(slug, src, dest)
    if nm.ambiguous:
        result.notes.append(
            'names given two different targets, left as written in text: '
            + '; '.join(f'{n} ({", ".join(t)})' for n, t in sorted(nm.ambiguous.items())))

    # Everything is built in memory first, so an error writes nothing
    files: dict[str, bytes] = {}
    tables: dict[str, tuple[list[str], list[list[str]]]] = {}
    unknown: dict[str, set[str]] = {}
    for name in IMPORTED_CSVS:
        path = os.path.join(src_ref, name)
        if not os.path.isfile(path):
            result.missing.append(f'reference/{name}')
            continue
        header, rows = _read_source_csv(slug, path, f'reference/{name}')
        rows = _map_csv(name, header, rows, nm, unknown)
        tables[name] = (header, rows)
        files[name] = _render_csv(header, rows).encode('utf-8')
    if nm is not EMPTY_MAP:
        unmapped = {k: v for k, v in unknown.items() if v}
        if unmapped:
            result.notes.append(
                'ids or names the name map lacks, left as written: '
                + '; '.join(f'{k} ({", ".join(sorted(v)[:8])}'
                            + (f' and {len(v) - 8} more' if len(v) > 8 else '') + ')'
                            for k, v in sorted(unmapped.items())))
    span = None
    if proj.range is not None:
        chapters = None
        if proj.range.kind == 'chapters':
            path = os.path.join(src_ref, CHAPTER_MAP)
            if not os.path.isfile(path):
                raise SourceError(f'source {slug}: range {proj.range.describe()!r} needs the '
                                  f'source\'s reference/{CHAPTER_MAP}, and it has none; give '
                                  f'the range as `scenes first-id..last-id`')
            header, rows = _read_source_csv(slug, path, f'reference/{CHAPTER_MAP}')
            rows = _map_csv(CHAPTER_MAP, header, rows, nm, unknown)
            files[CHAPTER_MAP] = _render_csv(header, rows).encode('utf-8')
            chapters = _as_dicts((header, rows))
        span = resolve_range(slug, proj.range,
                             sorted(_as_dicts(tables.get('scenes.csv')), key=_seq), chapters)
    for name in IMPORTED_DOCS:
        path = os.path.join(src_ref, name)
        if not os.path.isfile(path) or is_unfilled_template(path):
            continue
        try:
            with open(path, encoding='utf-8') as f:
                files[name] = nm.apply_text(f.read()).encode('utf-8')
        except (OSError, UnicodeDecodeError) as e:
            raise SourceError(f'source {slug}: reference/{name} could not be read ({e})') from e
    scenes_src = os.path.join(src, 'scenes')
    if os.path.isdir(scenes_src):
        for fn in sorted(os.listdir(scenes_src)):
            if fn.endswith('.md'):
                try:
                    with open(os.path.join(scenes_src, fn), 'rb') as f:
                        files[f'scenes/{fn}'] = f.read()   # the source's text, as written
                except OSError as e:
                    raise SourceError(f'source {slug}: scenes/{fn} could not be read ({e})') from e
                result.prose_files += 1
    files[SOURCE_BIBLE] = build_source_bible(slug, tables, nm, proj.range,
                                             span).encode('utf-8')

    result.files = files
    result.changed = _differs(dest, files)
    return result


# The registries `seed_registries` fills from the source (B-013): an
# adaptation starts from the source's cast and places, so the architecture
# and map stages have canonical ids to use instead of coining them.
SEEDED_REGISTRIES = ('characters.csv', 'locations.csv', 'values.csv')


def seed_registries(project_dir: str, cfg: SourceConfig) -> list[tuple[str, int]]:
    """Fill each of the project's own registries (`SEEDED_REGISTRIES`) that
    is missing or has no rows from the imported sources' copies, which
    already carry the name map. A registry with any row is the author's and
    is never touched. The project's header is kept (a column the source
    lacks, such as `pronouns`, is left empty; one only the source has is
    dropped); with no project file, the source's header is used. With
    several sources the first to give an id wins. Returns (file, rows
    written) for each registry seeded."""
    seeded = []
    ref = os.path.join(project_dir, 'reference')
    for name in SEEDED_REGISTRIES:
        own = os.path.join(ref, name)
        header: list[str] = []
        if os.path.isfile(own):
            try:
                header, rows, _problem = _read_rows(own)
            except (OSError, UnicodeDecodeError):
                continue  # unreadable: leave it for validate to report
            if rows:
                continue
        merged: dict[str, dict[str, str]] = {}
        src_header: list[str] = []
        for slug in cfg.slugs():
            path = os.path.join(source_dir(project_dir, slug), name)
            if not os.path.isfile(path):
                continue
            h, rows, problem = _read_rows(path)
            if problem or 'id' not in h:
                continue
            src_header = src_header or h
            for r in rows:
                row = dict(zip(h, r))
                if row['id'].strip() and row['id'] not in merged:
                    merged[row['id']] = row
        if not merged:
            continue
        header = header or src_header
        out = [[row.get(col, '') for col in header] for row in merged.values()]
        os.makedirs(ref, exist_ok=True)
        with open(own, 'w', encoding='utf-8', newline='') as f:
            f.write(_render_csv(header, out))
        seeded.append((f'reference/{name}', len(out)))
    return seeded


def write_import(result: ImportResult) -> None:
    """Swap a planned import in (only when it changes something)."""
    if result.changed:
        _replace_dir(result.dest, result.files)


def _differs(dest: str, files: dict[str, bytes]) -> bool:
    on_disk = set()
    if os.path.isdir(dest):
        for root, _dirs, names in os.walk(dest):
            for n in names:
                on_disk.add(os.path.relpath(os.path.join(root, n), dest).replace(os.sep, '/'))
    if on_disk != set(files):
        return True
    for rel, data in files.items():
        try:
            with open(os.path.join(dest, rel), 'rb') as f:
                if f.read() != data:
                    return True
        except OSError:
            return True   # unreadable: rewrite it
    return False


def _replace_dir(dest: str, files: dict[str, bytes]) -> None:
    """Write `files` to a sibling directory, then swap it in for `dest`."""
    parent = os.path.dirname(dest)
    os.makedirs(parent, exist_ok=True)
    tmp = dest + '.importing'
    old = dest + '.replaced'
    for d in (tmp, old):
        if os.path.isdir(d):
            shutil.rmtree(d)
    for rel, data in files.items():
        path = os.path.join(tmp, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'wb') as f:
            f.write(data)
    if os.path.isdir(dest):
        os.rename(dest, old)
    os.rename(tmp, dest)
    if os.path.isdir(old):
        shutil.rmtree(old)


# ============================================================================
# The source bible
# ============================================================================

def _as_dicts(table: tuple[list[str], list[list[str]]] | None) -> list[dict[str, str]]:
    if not table:
        return []
    header, rows = table
    return [dict(zip(header, r)) for r in rows]


def _seq(row: dict[str, str]) -> float:
    try:
        return float(row.get('seq', ''))
    except ValueError:
        return float('inf')


SPAN_PREFIX = 'Adapted span: '
_PART_HEADINGS = {'before': 'Before the adapted span', 'span': 'The adapted span',
                  'after': 'After the adapted span'}


def span_line(rng: SourceRange, span: list[str], total: int) -> str:
    """The bible's line naming the range it was built for (`check_bible_span`
    reads it back by its start, `SPAN_PREFIX` + the range + ` (`)."""
    return (f'{SPAN_PREFIX}{rng.describe()} ({len(span)} of the source\'s {total} scenes, '
            f'`{span[0]}` to `{span[-1]}`). This novel adapts only these. The scenes '
            f'before and after the span are context (what the characters know of the past, '
            f'and what comes later), listed briefly; they are not material to adapt.')


def build_source_bible(slug: str, tables: dict, nm: NameMap = EMPTY_MAP,
                       rng: SourceRange | None = None,
                       span: list[str] | None = None) -> str:
    """The source in one document, from its CSVs: the events in reading order
    with outcomes and value shifts, the cast with roles, the places, the
    threads and the timeline days.

    With a range (`rng` and its resolved `span`), the events are split into
    before / the adapted span / after: scenes in the span keep their outcome
    and value lines, the others are one line each (context, not material),
    and the cast is ordered and counted by the span. Places, threads and the
    timeline stay whole-source. Without one there is no `Adapted span:`
    line, one undivided events list, and whole-source cast counts."""
    scenes = sorted(_as_dicts(tables.get('scenes.csv')), key=_seq)
    in_span = set(span) if span is not None else None
    intent = {r.get('id', ''): r for r in _as_dicts(tables.get('scene-intent.csv'))}
    briefs = {r.get('id', ''): r for r in _as_dicts(tables.get('scene-briefs.csv'))}
    chars = _as_dicts(tables.get('characters.csv'))
    places = _as_dicts(tables.get('locations.csv'))
    threads = _as_dicts(tables.get('mice-threads.csv'))

    out = [f'# Source bible: {slug}', '',
           f'Generated by `storyforge source import` from the source\'s CSVs '
           f'(`reference/source/{slug}/`). Re-run the import to refresh it; don\'t edit it.']
    if nm.changed():
        out.append('Names follow the name map. The source prose '
                   f'(`reference/source/{slug}/scenes/`) keeps the translator\'s names.')
    if rng is not None and span:
        out.append(span_line(rng, span, len(scenes)))
    out += ['', f'## Events in reading order ({len(scenes)} scenes)', '']

    pov_count: dict[str, int] = {}
    on_stage_count: dict[str, int] = {}
    thread_scenes: dict[str, list[str]] = {}
    days: dict[str, list[str]] = {}
    # The span is a continuous run of reading order (resolve_range): the
    # events split at its first and last scene
    bounds = None
    if in_span:
        at = [i for i, x in enumerate(scenes) if x.get('id', '') in in_span]
        bounds = (at[0], at[-1])
    part = None
    for n, s in enumerate(scenes, 1):
        sid = s.get('id', '')
        it, br = intent.get(sid, {}), briefs.get(sid, {})
        inside = True
        if bounds:
            now = ('before' if n - 1 < bounds[0] else 'after' if n - 1 > bounds[1]
                   else 'span')
            inside = now == 'span'
            if now != part:
                count = {'before': bounds[0], 'span': bounds[1] - bounds[0] + 1,
                         'after': len(scenes) - bounds[1] - 1}[now]
                out += ([''] if part else []) + [f'### {_PART_HEADINGS[now]} ({count} scenes)', '']
                part = now
        what = s.get('summary', '').strip() or it.get('function', '').strip()
        facts = []
        day = s.get('timeline_day', '').strip()
        if day:
            facts.append(f'day {day}')
            days.setdefault(day, []).append(sid)
        if s.get('pov', '').strip():
            facts.append(f'POV {s["pov"].strip()}')
            if inside:
                pov_count[s['pov'].strip()] = pov_count.get(s['pov'].strip(), 0) + 1
        if s.get('location', '').strip():
            facts.append(s['location'].strip().replace(';', ', '))
        line = f'{n}. **{s.get("title", "").strip() or sid}** (`{sid}`'
        line += f'; {"; ".join(facts)})' if facts else ')'
        if what:
            line += f': {what}'
        out.append(line)
        tail = []
        # Outside the span a scene is context: its one line, no outcome or value
        if inside and br.get('outcome', '').strip():
            tail.append(f'Outcome: {br["outcome"].strip()}')
        value = it.get('value_at_stake', '').strip()
        shift = it.get('value_shift', '').strip()
        if inside and (value or shift):
            tail.append(f'Value: {value or "?"} {shift}'.rstrip())
        if tail:
            out.append(f'   {". ".join(tail)}.')
        for cid in filter(None, (c.strip() for c in it.get('on_stage', '').split(';'))):
            if inside:
                on_stage_count[cid] = on_stage_count.get(cid, 0) + 1
        for th in filter(None, (t.strip() for t in it.get('mice_threads', '').split(';'))):
            thread_scenes.setdefault(th.lstrip('+-'), []).append(sid)

    out += ['', f'## Cast ({len(chars)} characters'
            + ('; POV and on-stage counts are within the adapted span)' if bounds else ')'),
            '']
    for c in sorted(chars, key=lambda c: (-pov_count.get(c.get('id', ''), 0),
                                          -on_stage_count.get(c.get('id', ''), 0),
                                          c.get('id', ''))):
        cid = c.get('id', '')
        bits = [b for b in (c.get('role', '').strip(),
                            f'POV in {pov_count[cid]}' if pov_count.get(cid) else '',
                            f'on stage in {on_stage_count[cid]}' if on_stage_count.get(cid) else '')
                if b]
        aliases = c.get('aliases', '').strip()
        line = f'- **{c.get("name", "").strip() or cid}** (`{cid}`)'
        if bits:
            line += f': {", ".join(bits)}'
        if aliases:
            line += f'. Also: {aliases.replace(";", ", ")}'
        out.append(line)

    out += ['', f'## Places ({len(places)})', '']
    for p in places:
        line = f'- **{p.get("name", "").strip() or p.get("id", "")}** (`{p.get("id", "")}`)'
        if p.get('aliases', '').strip():
            line += f'. Also: {p["aliases"].strip().replace(";", ", ")}'
        out.append(line)

    out += ['', f'## Threads ({len(threads)})', '']
    for t in threads:
        tid = t.get('id', '')
        where = thread_scenes.get(tid, [])
        line = f'- **{t.get("name", "").strip() or tid}** (`{tid}`'
        line += f', {t["type"].strip()})' if t.get('type', '').strip() else ')'
        if where:
            line += f': opens in `{where[0]}`' + (f', last in `{where[-1]}`'
                                                  if len(where) > 1 else '')
            line += f' ({len(where)} scenes)'
        out.append(line)

    out += ['', '## Timeline', '']
    if days:
        def daykey(d):
            try:
                return (0, float(d))
            except ValueError:
                return (1, d)
        for d in sorted(days, key=daykey):
            out.append(f'- Day {d}: {", ".join(f"`{s}`" for s in days[d])}')
    else:
        out.append('(the source\'s scenes carry no timeline days)')
    return '\n'.join(out) + '\n'


# ============================================================================
# Reading an imported source
# ============================================================================

def read_table(project_dir: str, slug: str, name: str) -> list[dict[str, str]]:
    """An imported CSV as dicts ([] when it isn't there). Raises SourceError
    when it can't be read or a row has the wrong number of cells: the import
    writes well-formed files, so either means a hand edit to re-import over."""
    path = os.path.join(source_dir(project_dir, slug), name)
    if not os.path.isfile(path):
        return []
    header, rows = _read_source_csv(
        slug, path, f'reference/source/{slug}/{name} (re-run `storyforge source import`)')
    return [dict(zip(header, r)) for r in rows]


def source_scenes(project_dir: str, slug: str) -> list[dict[str, str]]:
    """The imported source's scenes in reading order."""
    return sorted(read_table(project_dir, slug, 'scenes.csv'), key=_seq)


def is_imported(project_dir: str, slug: str) -> bool:
    return os.path.isfile(os.path.join(source_dir(project_dir, slug), 'scenes.csv'))


def source_prose(project_dir: str, slug: str, scene_id: str) -> str | None:
    path = os.path.join(source_dir(project_dir, slug), 'scenes', f'{scene_id}.md')
    try:
        with open(path, encoding='utf-8') as f:
            return f.read().strip()
    except FileNotFoundError:
        return None


def require_imported(project_dir: str, cfg: SourceConfig) -> None:
    """Raise SourceError naming every source not imported yet: a prompt built
    without it would say the novel adapts a source and show none of it. Also
    raises for a source bible built for another `range:` (`check_bible_span`),
    and for a range the imported copy can't resolve (`adapted_ids`), so every
    caller's up-front check stops before any spend rather than mid-run."""
    missing = [s for s in cfg.slugs() if not is_imported(project_dir, s)]
    if missing:
        raise SourceError(f'source {", ".join(missing)} '
                          f'{"is" if len(missing) == 1 else "are"} not imported: '
                          f'run `storyforge source import`')
    for p in cfg.projects:
        check_bible_span(project_dir, p)
        if p.range is not None:
            adapted_ids(project_dir, cfg, p.slug)


def check_bible_span(project_dir: str, proj: SourceProject) -> None:
    """Raise SourceError when the imported source bible was built for another
    range than storyforge.yaml now gives (its `SPAN_PREFIX` line names the
    range; a bible built without one has no such line). A missing bible is
    `source_bibles`' to report."""
    path = os.path.join(source_dir(project_dir, proj.slug), SOURCE_BIBLE)
    try:
        with open(path, encoding='utf-8') as f:
            lines = f.read().splitlines()
    except FileNotFoundError:
        return
    except (OSError, UnicodeDecodeError) as e:
        raise SourceError(f'reference/source/{proj.slug}/{SOURCE_BIBLE} could not be read '
                          f'({e}); re-run `storyforge source import`') from e
    found = next((l for l in lines if l.startswith(SPAN_PREFIX)), None)
    if proj.range is None:
        stale = found is not None
    else:
        stale = found is None or not found.startswith(f'{SPAN_PREFIX}{proj.range.describe()} (')
    if stale:
        was = found[len(SPAN_PREFIX):].split(' (', 1)[0] if found else 'the whole source'
        now = proj.range.describe() if proj.range else 'the whole source'
        raise SourceError(f'source {proj.slug} was imported for {was}, but storyforge.yaml '
                          f'now adapts {now}: re-run `storyforge source import`')


# ----------------------------------------------------------------------------
# The range: which source scenes the novel adapts
# ----------------------------------------------------------------------------

def resolve_range(slug: str, rng: SourceRange, scenes: list[dict[str, str]],
                  chapters: list[dict[str, str]] | None) -> list[str]:
    """The scene ids `rng` covers, in reading order. `scenes` are the
    source's scenes in reading order; `chapters` its chapter-map rows (needed
    for a chapters range). Raises SourceError for an id that isn't a scene, a
    last scene before the first, a chapters range with no chapter map (or one
    without `chapter` and `scenes` columns), any chapter number the map lists
    twice, a chapter in the range the map doesn't have, chapters that list no
    scene or a scene not in scenes.csv, and chapters whose scenes aren't one
    continuous run of reading order (a scene listed twice included): a range
    is never silently narrowed or widened.

    A chapter map lists a Storyforge source's active scenes only, so a cut,
    merged or archived source scene (`INACTIVE_STATUSES`) between two of the
    chapters' scenes doesn't break the run; it is in the span, as a scenes
    range over the same stretch has it, and coverage asks for it as it does
    for every source scene. Map rows whose `chapter` isn't a number can't be
    named by a range; a run they break names them."""
    where = f'source {slug}: range {rng.describe()!r}'
    ids = [s.get('id', '').strip() for s in scenes]
    pos = {i: n for n, i in enumerate(ids) if i}
    if rng.kind == 'scenes':
        for end in (rng.first, rng.last):
            if end not in pos:
                hint = (' (a range of scenes is written `first-id..last-id`)'
                        if rng.first == rng.last and '-' in end else '')
                raise SourceError(f'{where}: {end} is not a scene of the source{hint}')
        a, b = pos[rng.first], pos[rng.last]
        if a > b:
            raise SourceError(f'{where} is inverted: {rng.last} comes before {rng.first} '
                              f'in the source\'s reading order')
        return [i for i in ids[a:b + 1] if i]
    if chapters is None:
        raise SourceError(f'{where}: the source has no reference/{CHAPTER_MAP}; give the '
                          f'range as `scenes first-id..last-id`')
    if chapters and not {'chapter', 'scenes'} <= set(chapters[0]):
        raise SourceError(f'{where}: reference/{CHAPTER_MAP} needs `chapter` and `scenes` '
                          f'columns')
    by_num: dict[int, dict] = {}
    unnumbered: list[str] = []
    for row in chapters:
        raw = row.get('chapter', '').strip()
        if not _ASCII_DIGITS.match(raw):
            unnumbered.append(raw or '(blank)')   # a range can't name it
            continue
        if int(raw) in by_num:
            raise SourceError(f'{where}: reference/{CHAPTER_MAP} lists chapter {raw} twice')
        by_num[int(raw)] = row
    wanted = range(int(rng.first), int(rng.last) + 1)
    absent = [str(n) for n in wanted if n not in by_num]
    if absent:
        raise SourceError(f'{where}: reference/{CHAPTER_MAP} has no chapter '
                          f'{", ".join(absent)}')
    members = [m for n in wanted for m in split_ids(by_num[n].get('scenes', ''))]
    if not members:
        raise SourceError(f'{where} is empty: its chapters list no scenes')
    unknown = [m for m in members if m not in pos]
    if unknown:
        raise SourceError(f'{where}: reference/{CHAPTER_MAP} lists scenes not in the '
                          f'source\'s scenes.csv: {", ".join(unknown[:8])}')
    lo, hi = min(pos[m] for m in members), max(pos[m] for m in members)
    span = [i for i in ids[lo:hi + 1] if i]
    inactive = {s.get('id', '').strip() for s in scenes[lo:hi + 1]
                if s.get('status', '').strip() in INACTIVE_STATUSES}
    twice = sorted({m for m in members if members.count(m) > 1})
    gaps = [i for i in span if i not in set(members) and i not in inactive]
    if twice or gaps:
        why = (f'lists {", ".join(twice[:8])} twice' if twice else
               f'skips {", ".join(gaps[:8])}, which lie between its first and last scene')
        if unnumbered:
            why += (f'; rows a range can\'t name (no chapter number): '
                    f'{", ".join(unnumbered[:8])}')
        raise SourceError(f'{where}: the chapter map\'s scenes for these chapters are not '
                          f'one continuous run of the source\'s reading order (it {why}); '
                          f'give the range as `scenes first-id..last-id`')
    return span


def adapted_ids(project_dir: str, cfg: SourceConfig, slug: str,
                scenes: list[dict[str, str]] | None = None) -> list[str] | None:
    """The imported source's scene ids the project's range covers, in reading
    order; None for a source with no range (all of it). Raises SourceError
    when the range can't be resolved against the imported copy (a chapters
    range whose chapter map wasn't imported: re-run the import)."""
    rng = cfg.project(slug).range
    if rng is None:
        return None
    if scenes is None:
        scenes = source_scenes(project_dir, slug)
    chapters = None
    if rng.kind == 'chapters':
        if not os.path.isfile(os.path.join(source_dir(project_dir, slug), CHAPTER_MAP)):
            raise SourceError(f'source {slug}: range {rng.describe()!r} needs '
                              f'reference/source/{slug}/{CHAPTER_MAP}: re-run '
                              f'`storyforge source import`')
        chapters = read_table(project_dir, slug, CHAPTER_MAP)
    return resolve_range(slug, rng, scenes, chapters)


def adapted_scenes(project_dir: str, cfg: SourceConfig, slug: str,
                   scenes: list[dict[str, str]] | None = None) -> list[dict[str, str]]:
    """The source's scenes being adapted, in reading order: all of them
    without a range."""
    if scenes is None:
        scenes = source_scenes(project_dir, slug)
    ids = adapted_ids(project_dir, cfg, slug, scenes)
    if ids is None:
        return scenes
    keep = set(ids)
    return [s for s in scenes if s.get('id', '').strip() in keep]


def spans(project_dir: str, cfg: SourceConfig) -> dict[str, frozenset[str] | None]:
    """{slug: the scene ids adapted} for every source; None for a source with
    no range. Raises SourceError as `adapted_ids` does."""
    out: dict[str, frozenset[str] | None] = {}
    for slug in cfg.slugs():
        ids = adapted_ids(project_dir, cfg, slug)
        out[slug] = None if ids is None else frozenset(ids)
    return out


def outside_range(hit: tuple[str, str], spans_: dict[str, frozenset[str] | None]) -> bool:
    """Whether a resolved (slug, id) falls outside its source's range."""
    span = spans_.get(hit[0])
    return span is not None and hit[1] not in span


def range_note(cfg: SourceConfig, slug: str) -> str:
    """'' for a source without a range, else e.g. 'chapters 1-4'."""
    rng = cfg.project(slug).range
    return rng.describe() if rng else ''


def source_bibles(project_dir: str, cfg: SourceConfig) -> list[tuple[str, str]]:
    """[(label, text)] of each source's bible, in yaml order. Raises
    SourceError for a source not imported, or a bible missing or unreadable."""
    require_imported(project_dir, cfg)
    out = []
    for slug in cfg.slugs():
        path = os.path.join(source_dir(project_dir, slug), SOURCE_BIBLE)
        try:
            with open(path, encoding='utf-8') as f:
                text = f.read().strip()
        except (OSError, UnicodeDecodeError) as e:
            raise SourceError(f'reference/source/{slug}/{SOURCE_BIBLE} could not be read '
                              f'({e}); re-run `storyforge source import`') from e
        out.append((f'Source Bible ({slug})', text))
    return out


def resolve_source_id(ref: str, catalogue: dict[str, dict[str, dict]]) -> tuple[str, str] | None:
    """(slug, scene id) for a `source_scenes` entry: `slug:id`, or a bare id
    found in exactly one source. None when it is in none, or in several."""
    if ':' in ref:
        slug, sid = ref.split(':', 1)
        return (slug, sid) if sid in catalogue.get(slug, {}) else None
    hits = [slug for slug, scenes in catalogue.items() if ref in scenes]
    return (hits[0], ref) if len(hits) == 1 else None


def catalogue(project_dir: str, cfg: SourceConfig) -> dict[str, dict[str, dict]]:
    """{slug: {scene id: scene row}} for every imported source."""
    return {slug: {r['id']: r for r in source_scenes(project_dir, slug) if r.get('id')}
            for slug in cfg.slugs()}


# ============================================================================
# Characters' pronouns (#515)
# ============================================================================

#: `Pronoun.origin` values
OWN, FROM_SOURCE, NO_PRONOUNS = 'own', 'source', 'none'
ORIGINS = (OWN, FROM_SOURCE, NO_PRONOUNS)
#: `Pronoun.match` values: the id, a name or alias, or no source row
MATCHES = ('id', 'name', '')


@dataclass(frozen=True)
class Pronoun:
    """One project character's pronouns and where they came from
    (`character_pronouns`). A reader uses `value`: it is what the character
    has, whatever the origin."""
    #: the cell as written, stripped ('' for none). OWN: the project's cell,
    #: readable or not (the readers report an unreadable one as before
    #: #515); FROM_SOURCE: a source value `schema.pronoun_key` reads
    value: str
    #: OWN (the project's characters.csv), FROM_SOURCE, or NO_PRONOUNS
    origin: str
    #: the source the value came from, or the first source with the matched
    #: row ('' when no source row matched)
    slug: str = ''
    #: how the source row was matched (`MATCHES`)
    match: str = ''
    #: every matched source value: ((slug, value as written), ...), in
    #: storyforge.yaml order, empty ones left out. Kept when the project's
    #: own value wins, so validate can compare them
    source_values: tuple[tuple[str, str], ...] = ()
    #: why no source row matched, when one could have ('' when nothing to
    #: say): a name several source characters share, a name another project
    #: character holds, a name two project characters claim. Only matters
    #: when the character has no own value
    note: str = ''
    #: what is wrong with the matched source rows' values ('' when nothing):
    #: a value `pronoun_key` can't read (never used), sources that disagree
    #: (none used). Reported whatever the origin
    problem: str = ''

    def __post_init__(self):
        from storyforge.schema import pronoun_key
        if self.origin not in ORIGINS or self.match not in MATCHES:
            raise ValueError(f'Pronoun origin {self.origin!r} / match {self.match!r}')
        if (self.origin == NO_PRONOUNS) == bool(self.value):
            raise ValueError(f'Pronoun {self.origin} with value {self.value!r}')
        if self.origin == FROM_SOURCE and not (
                pronoun_key(self.value) and self.slug and self.match):
            raise ValueError(f'source Pronoun {self.value!r} needs a readable value, '
                             f'a slug and a match')


@dataclass(frozen=True)
class CastPronouns:
    """`character_pronouns`: {project character id: Pronoun} (read-only),
    and what about the sources kept any of them from being read (`notes`)."""
    by_id: dict[str, Pronoun] = field(default_factory=dict)
    #: source-wide problems: a source not imported; an imported
    #: characters.csv missing, empty, without a pronouns column, or with
    #: rows that have no id
    notes: tuple[str, ...] = ()
    #: the project's `source.mode` ('' without a `source:` block)
    mode: str = ''

    @property
    def adaptation(self) -> bool:
        """The project has a `source:` block."""
        return bool(self.mode)

    def counts_line(self) -> str:
        """'Pronouns: 29 own, 31 from source odyssey, 2 none (mentes,
        noemon)': one "from source" part per source that gave a value, the
        characters with none by id (the first 10, then how many more)."""
        own = sum(1 for p in self.by_id.values() if p.origin == OWN)
        parts = [f'{own} own']
        by_slug: dict[str, int] = {}
        for p in self.by_id.values():
            if p.origin == FROM_SOURCE:
                by_slug[p.slug] = by_slug.get(p.slug, 0) + 1
        parts += [f'{n} from source {slug}' for slug, n in by_slug.items()]
        none = [cid for cid, p in self.by_id.items() if p.origin == NO_PRONOUNS]
        if none:
            shown = ', '.join(none[:10]) + (f' and {len(none) - 10} more'
                                             if len(none) > 10 else '')
            parts.append(f'{len(none)} none ({shown})')
        else:
            parts.append('0 none')
        return 'Pronouns: ' + ', '.join(parts)


def _name_keys(row: dict[str, str]) -> list[str]:
    """A registry row's name and aliases, lowercased with spacing collapsed
    (the ids are matched separately)."""
    names = [row.get('name') or '', *(row.get('aliases') or '').split(';')]
    out = []
    for n in names:
        n = ' '.join(n.split()).lower()
        if n and n not in out:
            out.append(n)
    return out


def _name_match(row: dict[str, str], by_name: dict[str, set[str]],
                project_ids: set[str]) -> tuple[str | None, str]:
    """(source id, '') for the one source character whose name or alias is
    one of the row's, else (None, why: '' when no name matched at all). A
    name two source ids share matches neither, and a source character the
    project has under its own id is that person, not this one."""
    keys = _name_keys(row)
    unique = {next(iter(by_name[n])) for n in keys if len(by_name.get(n, ())) == 1}
    shared = [n for n in keys if len(by_name.get(n, ())) > 1]
    taken = sorted(unique & project_ids)
    unique -= set(taken)
    if len(unique) == 1:
        return unique.pop(), ''
    if unique:
        return None, (f'its names match {len(unique)} source characters '
                      f'({", ".join(sorted(unique))}), so none is used')
    if shared:
        return None, '; '.join(
            f'{n!r} is the name of {len(by_name[n])} source characters '
            f'({", ".join(sorted(by_name[n]))})' for n in shared) + ', so none is used'
    if taken:
        return None, (f'its name is source character {", ".join(taken)}\'s, who is '
                      f'another character in characters.csv, so none is used')
    return None, ''


def character_pronouns(project_dir: str) -> CastPronouns:
    """Each project character's pronouns (reference/characters.csv, keyed by
    `id`, or `name` for a row with none; a later row with the same key
    wins), and where they came from:

    - the project's own `pronouns` cell when it isn't empty (OWN, as written,
      readable or not: the readers report an unreadable own value as before);
    - otherwise, for an adaptation, the imported source's
      (`reference/source/<slug>/characters.csv`, whose ids the import mapped
      to the project's). When any source has a row with the character's id,
      that is the match, and its value or none is the answer (no name match
      is tried). Only when no source has the id: the one source character,
      across every imported source, whose name or alias is one of the
      character's. A name two source ids share (the Homer map's Thoas,
      Laodice, Xanthus) matches neither, even when their values agree; so
      does a name another project character holds by id, or one two project
      characters both claim: a name match never guesses (`Pronoun.note`
      says why). Every imported source's characters count for the match,
      a source without a pronouns column included (it gives no values).
      One person in several sources has one id there (the map gives it):
      the first readable value in storyforge.yaml order is used, and
      sources whose readable values name different pronouns give none. A
      value `schema.pronoun_key` can't read is never used (`Pronoun.problem`
      says so for both);
    - otherwise NO_PRONOUNS.

    The source rows are matched even when the own value wins, so validate
    can compare them (`Pronoun.source_values`). Nothing is written.

    Without a `source:` block every character is OWN or NO_PRONOUNS from its
    own cell, exactly what the readers read before #515. Raises SourceError
    for a `source:` block that can't be used, or an imported characters.csv
    that can't be read; a source not imported yet is a note."""
    from storyforge.elaborate import _read_csv
    from storyforge.schema import pronoun_key
    rows: dict[str, dict[str, str]] = {}
    for row in _read_csv(os.path.join(project_dir, 'reference', 'characters.csv')):
        cid = (row.get('id') or '').strip() or (row.get('name') or '').strip()
        if cid:
            rows[cid] = row
    cfg = read_config(project_dir)

    # Every imported source character, by id (the project's id) and by name
    notes: list[str] = []
    by_id: dict[str, list[tuple[str, str]]] = {}      # id → [(slug, value)]
    by_name: dict[str, set[str]] = {}                 # name → {id}
    for slug in (cfg.slugs() if cfg else []):
        if not is_imported(project_dir, slug):
            notes.append(f'source {slug} is not imported, so no pronouns are read '
                         f'from it (run `storyforge source import`)')
            continue
        table = read_table(project_dir, slug, 'characters.csv')
        if not table:
            notes.append(f'reference/source/{slug}/characters.csv is missing or empty, '
                         f'so no pronouns are read from it')
            continue
        if 'pronouns' not in table[0]:
            notes.append(f'reference/source/{slug}/characters.csv has no pronouns '
                         f'column, so no pronouns are read from it')
        no_id = 0
        for srow in table:
            sid = (srow.get('id') or '').strip()
            if not sid:
                no_id += 1
                continue
            by_id.setdefault(sid, []).append((slug, (srow.get('pronouns') or '').strip()))
            for n in _name_keys(srow):
                by_name.setdefault(n, set()).add(sid)
        if no_id:
            notes.append(f'reference/source/{slug}/characters.csv has {no_id} row(s) with '
                         f'no id, so no pronouns are read from them')

    # Match each character to a source id; a source id two project
    # characters reach by name is neither's
    matched: dict[str, tuple[str | None, str, str]] = {}   # cid → (sid, match, note)
    for cid, row in rows.items():
        if cid in by_id:
            matched[cid] = (cid, 'id', '')
        elif by_id:
            sid, note = _name_match(row, by_name, set(rows))
            matched[cid] = (sid, 'name' if sid else '', note)
        else:
            matched[cid] = (None, '', '')
    claims: dict[str, list[str]] = {}
    for cid, (sid, match, _) in matched.items():
        if match == 'name':
            claims.setdefault(sid, []).append(cid)
    for sid, cids in claims.items():
        if len(cids) > 1:
            for cid in cids:
                matched[cid] = (None, '', f'source character {sid} matches {len(cids)} '
                                          f'characters by name ({", ".join(cids)}), so none '
                                          f'is used')

    out: dict[str, Pronoun] = {}
    for cid, row in rows.items():
        own = (row.get('pronouns') or '').strip()
        sid, match, note = matched[cid]
        hits = tuple((s, v) for s, v in by_id.get(sid, []) if v) if sid else ()
        slug = by_id[sid][0][0] if sid else ''
        readable = [(s, v) for s, v in hits if pronoun_key(v)]
        problems = [f'source {s} gives {v!r}, which is not a pronoun storyforge knows, '
                    f'so it is not used' for s, v in hits if pronoun_key(v) is None]
        value = ''
        if len({pronoun_key(v) for _, v in readable}) > 1:
            problems.append('the sources disagree (' + ', '.join(
                f'{s}: {v!r}' for s, v in readable) + '), so none is used')
        elif readable:
            slug, value = readable[0]
        problem = '; '.join(problems)
        if own:
            out[cid] = Pronoun(own, OWN, slug, match, hits, note, problem)
        elif value:
            out[cid] = Pronoun(value, FROM_SOURCE, slug, match, hits, '', problem)
        else:
            out[cid] = Pronoun('', NO_PRONOUNS, slug, match, hits, note, problem)
    return CastPronouns(out, tuple(notes), cfg.mode if cfg else '')


# ============================================================================
# The source map
# ============================================================================

def source_map_path(project_dir: str) -> str:
    return os.path.join(project_dir, 'reference', SOURCE_MAP)


def read_source_map(project_dir: str) -> list[dict[str, str]] | None:
    """The source map's rows, or None when there is no map yet. Raises
    SourceError for a header that isn't `SOURCE_MAP_COLUMNS` or a row with the
    wrong cell count."""
    path = source_map_path(project_dir)
    if not os.path.isfile(path):
        return None
    try:
        header, rows, problem = _read_rows(path)
    except (OSError, UnicodeDecodeError) as e:
        raise SourceError(f'reference/{SOURCE_MAP} could not be read ({e})') from e
    if header and header != SOURCE_MAP_COLUMNS:
        raise SourceError(f'reference/{SOURCE_MAP}: the header must be '
                          f'{"|".join(SOURCE_MAP_COLUMNS)}')
    if problem:
        raise SourceError(f'reference/{SOURCE_MAP}: {problem}')
    return [dict(zip(header, (c.strip() for c in r))) for r in rows]


def write_source_map(project_dir: str, rows: list[dict[str, str]]) -> None:
    """Write the map (LF, cells through csv_safe)."""
    lines = ['|'.join(SOURCE_MAP_COLUMNS)]
    for r in rows:
        lines.append('|'.join(csv_safe(r.get(c, '') or '') for c in SOURCE_MAP_COLUMNS))
    with open(source_map_path(project_dir), 'w', encoding='utf-8', newline='') as f:
        f.write('\n'.join(lines) + '\n')


def split_ids(cell: str) -> list[str]:
    return [t.strip() for t in (cell or '').split(';') if t.strip()]


def map_rows_by_scene(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    return {r['scene_id']: r for r in rows if r.get('scene_id')}


# ============================================================================
# Coverage (validate)
# ============================================================================

def _day(row: dict | None) -> float | None:
    try:
        return float((row or {}).get('timeline_day', ''))
    except ValueError:
        return None


def finding(severity: str, message: str, scene_id: str = '') -> dict:
    """A source finding in validate's shape (the keys `elaborate._check`
    findings carry, so a report mixing them reads either)."""
    if severity not in ('blocking', 'advisory'):
        raise ValueError(f'severity {severity!r}')
    return {'severity': severity, 'scene_id': scene_id, 'message': message,
            'check': 'source', 'category': 'source', 'passed': False}


# Scene statuses that take a scene out of the book (as elsewhere: chapter
# map freshness, schema); such a scene adapts nothing
INACTIVE_STATUSES = frozenset({'cut', 'merged', 'archived'})


def active_scenes(project_dir: str) -> list[dict[str, str]]:
    """The project's scenes in reading order, without cut/merged/archived."""
    from storyforge.elaborate import _read_csv
    rows = _read_csv(os.path.join(project_dir, 'reference', 'scenes.csv'))
    return sorted((r for r in rows if r.get('id')
                   and r.get('status', '').strip() not in INACTIVE_STATUSES), key=_seq)


def check_coverage(project_dir: str, cfg: SourceConfig) -> dict:
    """Validate's source check. Returns {'findings': [...], 'lines': [...],
    'checked': bool}, findings made by `finding`; `lines` are the coverage
    lines ("Source odyssey: 170 scenes, ..."). Coverage gaps (a source scene
    unaccounted for, or cut with no reason) take the mode's severity; a
    malformed or dangling row, an unknown id, a scene with no row, a source
    not imported, and an unusable map always block. A missing map and a
    reorder the source's timeline can't check are advisory.

    With a `range:`, only the range's source scenes need accounting for; a
    row adapting a scene outside it blocks in either mode (the map, briefs
    and fidelity prompts never show it), a cut row naming one is advisory
    (it needs no row), and a range that can't be resolved, or an import made
    for another range (or a missing source bible), blocks and leaves that
    source's coverage uncounted."""
    findings: list[dict] = []
    lines: list[str] = []

    def add(severity, message, scene_id=''):
        findings.append(finding(severity, message, scene_id))

    missing = [s for s in cfg.slugs() if not is_imported(project_dir, s)]
    for slug in missing:
        add('blocking', f'source {slug} is not imported: run `storyforge source import`')
    cat = {}
    spans_: dict[str, frozenset[str] | None] = {}   # as `spans`: None = whole source
    no_span: set[str] = set()   # an import or range coverage can't be counted against
    for slug in cfg.slugs():
        if slug in missing:
            continue
        try:
            rows_ = source_scenes(project_dir, slug)
        except SourceError as e:
            add('blocking', str(e))
            continue
        ids = [r.get('id', '').strip() for r in rows_]
        if '' in ids:
            add('blocking', f'source {slug}: {ids.count("")} scene(s) with no id')
        dupes = sorted({i for i in ids if i and ids.count(i) > 1})
        if dupes:
            add('blocking', f'source {slug}: duplicate scene ids {", ".join(dupes)}')
        cat[slug] = {r['id']: r for r in rows_ if r.get('id')}
        try:
            # An import made for another range (or none) is counted against
            # nothing: its bible and every prompt would disagree with the yaml
            if (cfg.project(slug).range is not None and not
                    os.path.isfile(os.path.join(source_dir(project_dir, slug), SOURCE_BIBLE))):
                raise SourceError(f'reference/source/{slug}/{SOURCE_BIBLE} is missing: '
                                  f're-run `storyforge source import`')
            check_bible_span(project_dir, cfg.project(slug))
            span = adapted_ids(project_dir, cfg, slug, rows_)
        except SourceError as e:
            # Coverage of a range that can't be resolved would be wrong either
            # way (the whole source, or nothing): it is not counted
            add('blocking', str(e))
            no_span.add(slug)
            continue
        spans_[slug] = None if span is None else frozenset(span)

    try:
        rows = read_source_map(project_dir)
    except SourceError as e:
        add('blocking', str(e))
        return {'findings': findings, 'lines': lines, 'checked': False}
    if rows is None:
        add('advisory', f'no reference/{SOURCE_MAP} yet (the map stage writes it); '
                        f'source coverage not checked')
        return {'findings': findings, 'lines': lines, 'checked': False}

    from storyforge.elaborate import _read_csv
    scenes = active_scenes(project_dir)
    scene_ids = [s['id'] for s in scenes]
    inactive = {r['id'] for r in _read_csv(os.path.join(project_dir, 'reference', 'scenes.csv'))
                if r.get('id') and r.get('status', '').strip() in INACTIVE_STATUSES}
    gap = cfg.gap_severity

    covered: dict[tuple[str, str], list[dict]] = {}
    mapped_scenes = set()
    for n, r in enumerate(rows, 1):
        sid, treatment = r.get('scene_id', ''), r.get('treatment', '')
        where = sid or f'{SOURCE_MAP} row {n}'
        if treatment not in TREATMENTS:
            add('blocking', f'treatment {treatment!r} is not one of {", ".join(TREATMENTS)}',
                where)
            continue
        refs = split_ids(r.get('source_scenes', ''))
        if treatment == 'cut':
            if sid:
                add('blocking', 'a cut row must have an empty scene_id (the source '
                                'scene goes in source_scenes)', where)
            if not refs:
                add('blocking', 'a cut row names no source scene', where)
        else:
            if not sid:
                add('blocking', f'a {treatment} row has no scene_id', where)
                continue
            if sid in mapped_scenes:
                add('blocking', 'more than one row in the source map', sid)
            mapped_scenes.add(sid)
            if sid in inactive:
                # A cut or merged scene adapts nothing: its source scenes
                # need another home or a cut row
                add('advisory', 'is cut or merged in scenes.csv; its source map row '
                                'covers nothing', sid)
                continue
            if sid not in scene_ids:
                add('blocking', 'in the source map but not in scenes.csv', sid)
            if not refs and treatment != 'invent':
                add('blocking', f'a {treatment} row names no source scene '
                                f'(a scene with no source is `invent`)', sid)
            if refs and treatment == 'invent':
                add('blocking', 'an invent row names source scenes '
                                '(use the treatment that adapts them)', sid)
        for ref in refs:
            hit = resolve_source_id(ref, cat)
            if hit is None:
                where_found = [s for s, c in cat.items() if ref in c]
                slug = ref.split(':', 1)[0] if ':' in ref else ''
                if len(where_found) > 1:
                    why = (f'is in more than one source ({", ".join(where_found)}); '
                           f'write it as slug:id')
                elif slug and slug not in cat:
                    why = f'names a source ({slug}) that isn\'t imported or configured'
                else:
                    why = 'is not a scene of the source'

                add('blocking', f'source scene {ref} {why}', where)
                continue
            if outside_range(hit, spans_):
                desc = range_note(cfg, hit[0])
                if treatment == 'cut':
                    add('advisory', f'source scene {ref} is outside the adapted range '
                                    f'({hit[0]}: {desc}), so it needs no cut row', where)
                else:
                    add('blocking', f'source scene {ref} is outside the adapted range '
                                    f'({hit[0]}: {desc}); widen `range` in storyforge.yaml '
                                    f'or adapt a scene inside it', where)
                continue
            covered.setdefault(hit, []).append(r)

    for sid in scene_ids:
        if sid not in mapped_scenes:
            add('blocking', 'has no row in the source map (an original scene is `invent`)',
                sid)

    # Every source scene being adapted (the range's, or all) is accounted for
    for slug, src in cat.items():
        if slug in no_span:
            lines.append(f'Source {slug}: coverage not checked (its import or range can\'t '
                         f'be used; see the finding)')
            continue
        span = spans_.get(slug)
        counts = {'mapped': 0, 'compressed': 0, 'cut': 0, 'cut_no_reason': 0,
                  'missing': 0}
        for src_id in src:
            if span is not None and src_id not in span:
                continue
            uses = covered.get((slug, src_id), [])
            kept = [u for u in uses if u.get('treatment') != 'cut']
            cuts = [u for u in uses if u.get('treatment') == 'cut']
            if kept and cuts:
                add('blocking', f'source scene {slug}:{src_id} is both adapted and cut')
            if kept:
                counts['mapped'] += 1
                if any(u.get('treatment') == 'compress' for u in kept):
                    counts['compressed'] += 1
            elif cuts:
                counts['cut'] += 1
                if not any(u.get('note', '').strip() for u in cuts):
                    counts['cut_no_reason'] += 1
                    add(gap, f'source scene {slug}:{src_id} is cut with no reason '
                             f'(give one in the note)')
            else:
                counts['missing'] += 1
                add(gap, f'source scene {slug}:{src_id} is not in the source map '
                         f'(adapt it, or cut it with a reason)')
        cut_part = f'{counts["cut"]} cut'
        if counts['cut']:
            cut_part += (' (reasons given)' if not counts['cut_no_reason']
                         else f' ({counts["cut_no_reason"]} without a reason)')
        size = (f'{len(src)} scenes' if span is None else
                f'{len(span)} of {len(src)} scenes adapted ({range_note(cfg, slug)})')
        line = (f'Source {slug}: {size}, {counts["mapped"]} mapped, '
                f'{counts["compressed"]} compressed, {cut_part}')
        if counts['missing']:
            line += f', {counts["missing"]} unaccounted for'
        lines.append(line)

    if cfg.mode == 'faithful':
        _check_reorders(rows, scenes, cat, add)
    return {'findings': findings, 'lines': lines, 'checked': True}


def _check_reorders(rows, scenes, cat, add) -> None:
    """In faithful mode, a `reorder` that crosses a source timeline anchor (its
    source day is earlier than a scene before it, or later than one after it,
    in the adaptation's order) needs a note saying why. Days are compared
    only within one source: two books' calendars are unrelated. A reorder
    whose source scenes carry no day can't be checked, and is said."""
    by_scene = map_rows_by_scene(rows)
    # Per scene, in reading order: {slug: its earliest source day}
    seq_days: list[tuple[str, dict[str, float]]] = []
    for s in scenes:
        r = by_scene.get(s.get('id', ''))
        days: dict[str, float] = {}
        for ref in split_ids((r or {}).get('source_scenes', '')):
            hit = resolve_source_id(ref, cat)
            d = _day(cat[hit[0]][hit[1]]) if hit else None
            if d is not None:
                days[hit[0]] = min(d, days.get(hit[0], d))
        seq_days.append((s.get('id', ''), days))
    for i, (sid, days) in enumerate(seq_days):
        r = by_scene.get(sid)
        if not r or r.get('treatment') != 'reorder':
            continue
        if not days:
            add('advisory', 'a reorder not checked against the source\'s timeline: '
                            'its source scenes carry no timeline_day', sid)
            continue
        for slug, day in days.items():
            before = [d[slug] for _, d in seq_days[:i] if slug in d]
            after = [d[slug] for _, d in seq_days[i + 1:] if slug in d]
            crosses = (before and day < max(before)) or (after and day > min(after))
            if crosses and not r.get('note', '').strip():
                add('blocking', f'reordered across the source\'s timeline ({slug} day '
                                f'{day:g}) with no note saying why', sid)
                break
