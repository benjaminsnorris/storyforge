"""Adaptation: a project built on a source project (#477).

A project whose `storyforge.yaml` has a `source:` block adapts another
Storyforge project (an extracted book, an earlier draft): a retelling, an
expansion, a rewrite. This module holds everything deterministic about that:

- `read_config`: the `source:` block (`SourceConfig`), or None without one.
- `load_name_map` / `NameMap`: the retelling's names
  (`source_id|target_id|source_name|target_name`). Ids, names and aliases
  are mapped by id; every text field gets whole-word, case-sensitive name
  replacement, longest name first. A row with an empty `source_id` is a
  text-only form (Ilius -> Ilium, "son of Saturn").
- `import_source`: copies a source project's scene CSVs, registries, ledger,
  structural CSVs and bibles into `reference/source/<slug>/` with the map
  applied, copies its prose (`scenes/*.md`) byte for byte, and writes
  `source-bible.md`. It writes nothing outside `reference/source/<slug>/`.
- `read_source_map` / `check_coverage`: `reference/source-map.csv`, which the
  map stage writes, and validate's coverage check of it.

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

MODES = ('faithful', 'free')
DEFAULT_MODE = 'faithful'

TREATMENTS = ('dramatize', 'compress', 'expand', 'pov-shift', 'reorder',
              'invent', 'cut')

SOURCE_MAP = 'source-map.csv'
SOURCE_MAP_COLUMNS = ['scene_id', 'source_scenes', 'treatment', 'note']

NAME_MAP_COLUMNS = ['source_id', 'target_id', 'source_name', 'target_name']

SOURCE_BIBLE = 'source-bible.md'

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
# lowercase ids in the remaining id columns are never touched.
_ID_COLUMNS = frozenset({'pov', 'location', 'characters', 'on_stage',
                         'subject', 'known_by'})
_REGISTRIES = ('characters.csv', 'locations.csv')


class SourceError(Exception):
    """A `source:` block, name map or source project that can't be used."""


# ============================================================================
# The `source:` block
# ============================================================================

@dataclass(frozen=True)
class SourceProject:
    slug: str
    path: str            # as written: relative to the project, or absolute
    name_map: str = ''   # a per-source override of SourceConfig.name_map


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

    def map_path(self, project: SourceProject) -> str:
        return project.name_map or self.name_map

    @property
    def blocking(self) -> str:
        """The severity of a coverage gap under this mode."""
        return 'blocking' if self.mode == 'faithful' else 'advisory'


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
            items[-1][kv.group(1)] = parse_yaml_scalar(kv.group(2))
        elif kv:
            raise SourceError('storyforge.yaml: `source.projects` entries start '
                              'with `- slug: ...`')
    return items


def read_config(project_dir: str) -> SourceConfig | None:
    """The project's `source:` block, or None when it has none.

    Raises SourceError for a block that can't be used: no projects, a project
    without a slug or path, a repeated or malformed slug, or an unknown mode.
    `mode` defaults to faithful; `name_map` and `rules` to nothing.
    """
    block = _source_block(project_dir)
    if block is None:
        return None
    items = _parse_projects(block)
    if not items:
        raise SourceError('storyforge.yaml: the `source:` block lists no '
                          '`projects` (each `- slug: ...` with a `path: ...`)')
    projects = []
    seen = set()
    for n, item in enumerate(items, 1):
        slug = item.get('slug', '').strip()
        path = item.get('path', '').strip()
        if not slug or not path:
            raise SourceError(f'storyforge.yaml: source project {n} needs both '
                              f'`slug` and `path`')
        if not _SLUG_RE.match(slug):
            raise SourceError(f'storyforge.yaml: source slug {slug!r} must be '
                              f'lowercase letters, digits and hyphens')
        if slug in seen:
            raise SourceError(f'storyforge.yaml: source slug {slug!r} is listed twice')
        seen.add(slug)
        projects.append(SourceProject(slug, path, item.get('name_map', '').strip()))
    keys = _direct_keys(block)
    mode = keys.get('mode') or DEFAULT_MODE
    if mode not in MODES:
        raise SourceError(f'storyforge.yaml: source.mode is {mode!r}; '
                          f'use one of {", ".join(MODES)}')
    return SourceConfig(
        projects=tuple(projects),
        name_map=keys.get('name_map', ''),
        mode=mode,
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
        if len(line) - len(line.lstrip()) != indent:
            continue
        m = re.match(r'^\s+(\w+):\s*(.*)$', line)
        if m:
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

@dataclass
class NameMap:
    ids: dict[str, str] = field(default_factory=dict)            # source_id -> target_id
    id_names: dict[str, str] = field(default_factory=dict)       # source_id -> target_name
    replacements: dict[str, str] = field(default_factory=dict)   # source_name -> target_name
    ambiguous: dict[str, list[str]] = field(default_factory=dict)  # name -> its targets
    path: str = ''

    def __post_init__(self):
        self._pattern = None

    def changed(self) -> list[tuple[str, str]]:
        """The names the map changes, longest first."""
        return sorted(((s, t) for s, t in self.replacements.items() if s != t),
                      key=lambda p: (-len(p[0]), p[0]))

    def apply_text(self, text: str) -> str:
        """Replace each source name with its target name: whole words,
        case-sensitive, longest first (one pass, so a replacement is never
        replaced again)."""
        changed = self.changed()
        if not changed or not text:
            return text
        if self._pattern is None:
            alternation = '|'.join(re.escape(s) for s, _ in changed)
            self._pattern = re.compile(rf'(?<!\w)(?:{alternation})(?!\w)')
        return self._pattern.sub(lambda m: self.replacements[m.group(0)], text)

    def map_ids(self, cell: str) -> str:
        """Map each `;`-separated id in a cell; ids the map lacks stay."""
        if not cell or not self.ids:
            return cell
        return ';'.join(self.ids.get(tok.strip(), tok.strip()) if tok.strip() else tok
                        for tok in cell.split(';'))


EMPTY_MAP = NameMap()


def load_name_map(path: str) -> NameMap:
    """Read a name map. Raises SourceError for a header that isn't exactly
    `NAME_MAP_COLUMNS`, a row with the wrong cell count, a registry row
    without a target id or name, a source id given two targets, or a
    text-only row (empty `source_id`) without both names.

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
    nm = NameMap(path=path)
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
            if sid in nm.ids and nm.ids[sid] != tid:
                raise SourceError(f'name map {path} line {n}: {sid} maps to both '
                                  f'{nm.ids[sid]} and {tid}')
            nm.ids[sid] = tid
            nm.id_names[sid] = tname
        elif not sname or not tname:
            raise SourceError(f'name map {path} line {n}: a text-only row (no '
                              f'source_id) needs a source_name and a target_name')
        if sname:
            targets_of.setdefault(sname, set()).add(tname)
    for sname, targets in targets_of.items():
        if len(targets) == 1:
            nm.replacements[sname] = next(iter(targets))
        else:
            nm.ambiguous[sname] = sorted(targets)
    return nm


# ============================================================================
# Import
# ============================================================================

@dataclass
class ImportResult:
    slug: str
    source_path: str
    dest: str
    files: list[str] = field(default_factory=list)       # relative to dest
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


def _map_csv(name: str, header: list[str], rows: list[list[str]],
             nm: NameMap) -> list[list[str]]:
    out = []
    id_idx = header.index('id') if 'id' in header else None
    name_idx = header.index('name') if 'name' in header else None
    for row in rows:
        new = []
        source_id = row[id_idx].strip() if id_idx is not None else ''
        for col, cell in zip(header, row):
            if name in _REGISTRIES and col == 'id':
                new.append(nm.map_ids(cell))
            elif col in _ID_COLUMNS:
                new.append(nm.map_ids(cell))
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


def map_gaps(src_ref: str, nm: NameMap) -> list[str]:
    """Registry ids (characters, locations) the map has no row for. Every
    registry entry needs one, even an unchanged name: a missing row is a gap,
    not a pass-through."""
    gaps = []
    for reg in _REGISTRIES:
        path = os.path.join(src_ref, reg)
        if not os.path.isfile(path):
            continue
        header, rows, _ = _read_rows(path)
        if 'id' not in header:
            continue
        i = header.index('id')
        gaps += [f'{reg}:{r[i]}' for r in rows
                 if i < len(r) and r[i].strip() and r[i].strip() not in nm.ids]
    return gaps


def import_source(project_dir: str, cfg: SourceConfig, slug: str,
                  dry_run: bool = False) -> ImportResult:
    """Copy one source project into `reference/source/<slug>/`, replacing
    what was there. Nothing outside that directory is written. Raises
    SourceError (before writing anything) when the source isn't a Storyforge
    project, a file it should copy is unreadable or malformed, or the name
    map can't be used or lacks a registry entry."""
    proj = cfg.project(slug)
    src = resolve(project_dir, proj.path)
    src_ref = os.path.join(src, 'reference')
    if os.path.realpath(src) == os.path.realpath(project_dir):
        raise SourceError(f'source {slug}: the path is this project itself')
    if not os.path.isfile(os.path.join(src_ref, 'scenes.csv')):
        raise SourceError(f'source {slug}: {src} has no reference/scenes.csv; '
                          f'is it a Storyforge project?')

    map_rel = cfg.map_path(proj)
    nm = EMPTY_MAP
    if map_rel:
        map_path = resolve(project_dir, map_rel)
        if not os.path.isfile(map_path):
            raise SourceError(f'source {slug}: name map {map_rel} not found')
        nm = load_name_map(map_path)
        gaps = map_gaps(src_ref, nm)
        if gaps:
            shown = ', '.join(gaps[:12]) + (f' and {len(gaps) - 12} more'
                                            if len(gaps) > 12 else '')
            raise SourceError(f'source {slug}: the name map has no row for '
                              f'{len(gaps)} registry entr{"y" if len(gaps) == 1 else "ies"} '
                              f'({shown}); add a row for each, even an unchanged name')

    dest = source_dir(project_dir, slug)
    result = ImportResult(slug, src, dest)
    if nm.ambiguous:
        result.notes.append(
            'names given two different targets, left as written in text: '
            + '; '.join(f'{n} ({", ".join(t)})' for n, t in sorted(nm.ambiguous.items())))

    # Everything is built in memory first, so an error writes nothing
    files: dict[str, bytes] = {}
    tables: dict[str, tuple[list[str], list[list[str]]]] = {}
    for name in IMPORTED_CSVS:
        path = os.path.join(src_ref, name)
        if not os.path.isfile(path):
            result.missing.append(f'reference/{name}')
            continue
        try:
            header, rows, problem = _read_rows(path)
        except (OSError, UnicodeDecodeError) as e:
            raise SourceError(f'source {slug}: reference/{name} could not be read ({e})') from e
        if problem:
            raise SourceError(f'source {slug}: reference/{name}: {problem}')
        rows = _map_csv(name, header, rows, nm)
        tables[name] = (header, rows)
        files[name] = _render_csv(header, rows).encode('utf-8')
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
                with open(os.path.join(scenes_src, fn), 'rb') as f:
                    files[f'scenes/{fn}'] = f.read()   # the translator's text, as written
                result.prose_files += 1
    files[SOURCE_BIBLE] = build_source_bible(slug, tables, nm).encode('utf-8')

    result.files = sorted(files)
    result.changed = _differs(dest, files)
    if dry_run or not result.changed:
        return result
    _replace_dir(dest, files)
    return result


def _differs(dest: str, files: dict[str, bytes]) -> bool:
    on_disk = set()
    if os.path.isdir(dest):
        for root, _dirs, names in os.walk(dest):
            for n in names:
                on_disk.add(os.path.relpath(os.path.join(root, n), dest).replace(os.sep, '/'))
    if on_disk != set(files):
        return True
    for rel, data in files.items():
        with open(os.path.join(dest, rel), 'rb') as f:
            if f.read() != data:
                return True
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


def build_source_bible(slug: str, tables: dict, nm: NameMap = EMPTY_MAP) -> str:
    """The source in one document, from its CSVs: the events in reading order
    with outcomes and value shifts, the cast with roles, the places, the
    threads and the timeline days."""
    scenes = sorted(_as_dicts(tables.get('scenes.csv')), key=_seq)
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
    out += ['', f'## Events in reading order ({len(scenes)} scenes)', '']

    pov_count: dict[str, int] = {}
    on_stage_count: dict[str, int] = {}
    thread_scenes: dict[str, list[str]] = {}
    days: dict[str, list[str]] = {}
    for n, s in enumerate(scenes, 1):
        sid = s.get('id', '')
        it, br = intent.get(sid, {}), briefs.get(sid, {})
        what = s.get('summary', '').strip() or it.get('function', '').strip()
        facts = []
        day = s.get('timeline_day', '').strip()
        if day:
            facts.append(f'day {day}')
            days.setdefault(day, []).append(sid)
        if s.get('pov', '').strip():
            facts.append(f'POV {s["pov"].strip()}')
            pov_count[s['pov'].strip()] = pov_count.get(s['pov'].strip(), 0) + 1
        if s.get('location', '').strip():
            facts.append(s['location'].strip().replace(';', ', '))
        line = f'{n}. **{s.get("title", "").strip() or sid}** (`{sid}`'
        line += f'; {"; ".join(facts)})' if facts else ')'
        if what:
            line += f': {what}'
        out.append(line)
        tail = []
        if br.get('outcome', '').strip():
            tail.append(f'Outcome: {br["outcome"].strip()}')
        value = it.get('value_at_stake', '').strip()
        shift = it.get('value_shift', '').strip()
        if value or shift:
            tail.append(f'Value: {value or "?"} {shift}'.rstrip())
        if tail:
            out.append(f'   {". ".join(tail)}.')
        for cid in filter(None, (c.strip() for c in it.get('on_stage', '').split(';'))):
            on_stage_count[cid] = on_stage_count.get(cid, 0) + 1
        for th in filter(None, (t.strip() for t in it.get('mice_threads', '').split(';'))):
            thread_scenes.setdefault(th.lstrip('+-'), []).append(sid)

    out += ['', f'## Cast ({len(chars)} characters)', '']
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
    """An imported CSV as dicts ([] when it isn't there)."""
    path = os.path.join(source_dir(project_dir, slug), name)
    if not os.path.isfile(path):
        return []
    header, rows, _ = _read_rows(path)
    return [dict(zip(header, r + [''] * (len(header) - len(r)))) for r in rows]


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


def source_bibles(project_dir: str, cfg: SourceConfig) -> list[tuple[str, str]]:
    """[(label, text)] of each imported source's bible, in yaml order."""
    out = []
    for slug in cfg.slugs():
        path = os.path.join(source_dir(project_dir, slug), SOURCE_BIBLE)
        try:
            with open(path, encoding='utf-8') as f:
                text = f.read().strip()
        except FileNotFoundError:
            continue
        if text:
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


def check_coverage(project_dir: str, cfg: SourceConfig) -> dict:
    """Validate's source check. Returns {'findings': [...], 'lines': [...],
    'checked': bool}. Each finding is {'severity', 'scene_id', 'message'} in
    validate's shape; `lines` are the coverage lines ("Source odyssey: 170
    scenes, ..."). What can't be checked is said as an advisory finding."""
    findings: list[dict] = []
    lines: list[str] = []

    def add(severity, message, scene_id=''):
        findings.append({'severity': severity, 'scene_id': scene_id,
                         'message': message, 'check': 'source'})

    missing = [s for s in cfg.slugs() if not is_imported(project_dir, s)]
    for slug in missing:
        add('blocking', f'source {slug} is not imported: run `storyforge source import`')
    cat = {s: c for s, c in catalogue(project_dir, cfg).items() if s not in missing}

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
    scenes = sorted(_read_csv(os.path.join(project_dir, 'reference', 'scenes.csv')),
                    key=_seq)
    scene_ids = [s.get('id', '') for s in scenes if s.get('id')]
    gap = cfg.blocking

    covered: dict[tuple[str, str], list[dict]] = {}
    mapped_scenes = set()
    for n, r in enumerate(rows, 2):
        sid, treatment, note = r.get('scene_id', ''), r.get('treatment', ''), r.get('note', '')
        where = sid or f'{SOURCE_MAP} line {n}'
        if treatment not in TREATMENTS:
            add('blocking', f'treatment {treatment!r} is not one of {", ".join(TREATMENTS)}',
                where)
            continue
        refs = split_ids(r.get('source_scenes', ''))
        if treatment == 'cut':
            if sid:
                add('blocking', 'a cut row has an empty scene_id (the source scene '
                                'is in source_scenes)', where)
            if not refs:
                add('blocking', 'a cut row names no source scene', where)
        else:
            if not sid:
                add('blocking', f'a {treatment} row has no scene_id', where)
                continue
            if sid in mapped_scenes:
                add('blocking', 'more than one row in the source map', sid)
            mapped_scenes.add(sid)
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
                why = (f'is in more than one source ({", ".join(where_found)}); '
                       f'write it as slug:id' if len(where_found) > 1
                       else 'is not a scene of the source')
                add('blocking', f'source scene {ref} {why}', where)
                continue
            covered.setdefault(hit, []).append(r)

    for sid in scene_ids:
        if sid not in mapped_scenes:
            add('blocking', 'has no row in the source map (an original scene is `invent`)',
                sid)

    # Every source scene is accounted for
    for slug, src in cat.items():
        counts = {'mapped': 0, 'compressed': 0, 'cut': 0, 'cut_no_reason': 0,
                  'missing': 0}
        for src_id in src:
            uses = covered.get((slug, src_id), [])
            kept = [u for u in uses if u.get('treatment') != 'cut']
            cuts = [u for u in uses if u.get('treatment') == 'cut']
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
        line = (f'Source {slug}: {len(src)} scenes, {counts["mapped"]} mapped, '
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
    in the adaptation's order) needs a note saying why."""
    by_scene = map_rows_by_scene(rows)
    seq_days: list[tuple[str, float | None]] = []
    for s in scenes:
        r = by_scene.get(s.get('id', ''))
        days = []
        for ref in split_ids((r or {}).get('source_scenes', '')):
            hit = resolve_source_id(ref, cat)
            d = _day(cat[hit[0]][hit[1]]) if hit else None
            if d is not None:
                days.append(d)
        seq_days.append((s.get('id', ''), min(days) if days else None))
    for i, (sid, day) in enumerate(seq_days):
        r = by_scene.get(sid)
        if not r or r.get('treatment') != 'reorder' or day is None:
            continue
        before = [d for _, d in seq_days[:i] if d is not None]
        after = [d for _, d in seq_days[i + 1:] if d is not None]
        crosses = (before and day < max(before)) or (after and day > min(after))
        if crosses and not r.get('note', '').strip():
            add('blocking', f'reordered across the source\'s timeline (source day '
                            f'{day:g}) with no note saying why', sid)
