"""The export bundle: one canonical JSON document of a book's structured state.

Plan §3.5. Storygild and Bookshelf read the bundle instead of the project's
files, and pin `schema_version`. Bookshelf reads its `dashboard_data` (pinned
at that section's own `schema_version`): `publish` builds the bundle and sends
that section; the prose and images travel in the publish manifest. The contract is in docs/agent-reference.md
("Export bundle"); `tests/test_export.py` pins its keys.

What goes in:

- `tables`: every CSV the bundle carries, keyed by its path relative to the
  project, each stored losslessly (header and rows as lists of strings exactly
  as in the file, plus its line ending, final newline and BOM), so
  `tables_from_bundle` writes each one back byte-for-byte:
    - `reference/*.csv` (kind `reference`): scenes, intent, briefs, the
      registries (characters, locations, values, mice-threads, motif-taxonomy,
      themes, ...), `commitments.csv`, the chapter map, voice profile,
      spine/architecture and whatever other registry the book keeps. The
      timeline calendar lives here too (`scenes.csv` `timeline_day` /
      `time_mode`).
    - the latest complete score cycle's CSVs (kind `scores`;
      `project.latest_scores`, named in `score_cycle`), plus
      `working/scores/structural-latest.csv`. Non-CSV files there (the HTML
      report) are not tables and are left out.
    - `working/timeline*.csv` (kind `timeline`): the timeline's stored cues.
    - `working/audit*.csv` and the CSVs under `working/audit/` (kind
      `audit`), as raw rows. PROVISIONAL: empty until the audit log
      (`working/audit-log.csv`, another PR) exists; the bundle passes through
      whatever CSVs are there, and names any non-CSV file under
      `working/audit/` in `warnings`.
- `dashboard_data`: `visualize.load_dashboard_data`'s output, unchanged,
  with its own `schema_version`.
- `project`: title, genre, medium and phase from storyforge.yaml;
  `storyforge_version`: the plugin version that wrote the bundle.
- `warnings`: every file the bundle meant to carry and couldn't (unreadable,
  not UTF-8), and anything about a table a consumer should know (mixed line
  endings). Empty means everything was read.

What stays out: scene prose (`scenes/*.md`) and manuscripts (`produce` and
`assemble` own those), score history beyond the latest cycle, and eval
results, though plan §3.5 lists them — evals measure Storyforge, not the
book, and their results belong to the Storyforge repo (`evals/results/`).

`schema_version` is a major version. Adding a key, a table kind or a table
doesn't change it. Renaming or removing a key, or changing a value's type,
bumps it, and the bundle changes in the same commit as any such change.
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
import tempfile

from storyforge import ledger
from storyforge.common import get_medium, get_plugin_dir, read_yaml_field

#: Major version of the bundle's shape (see module docstring).
SCHEMA_VERSION = 1

DEFAULT_OUTPUT = os.path.join('working', 'export', 'bundle.json')

_BOM = '﻿'


# ============================================================================
# Tables
# ============================================================================

def parse_table(text: str) -> dict:
    """A CSV's text as a lossless table: `header` and `rows` (lists of the
    cells between `|`, untouched), `line_ending`, `final_newline`, `bom`.

    Rows split on CRLF only when every newline is CRLF; otherwise on LF, so a
    stray CR stays inside its cell and the text still comes back exactly.
    Blank lines are kept as rows of one empty cell.
    """
    bom = text.startswith(_BOM)
    if bom:
        text = text[len(_BOM):]
    crlf = '\n' in text and text.count('\r\n') == text.count('\n')
    eol = '\r\n' if crlf else '\n'
    final_newline = text.endswith(eol)
    body = text[:-len(eol)] if final_newline else text
    lines = body.split(eol) if (body or final_newline) else []
    cells = [line.split('|') for line in lines]
    return {
        'header': cells[0] if cells else [],
        'rows': cells[1:],
        'line_ending': eol,
        'final_newline': final_newline,
        'bom': bom,
    }


def table_text(table: dict) -> str:
    """The exact text `parse_table` read."""
    lines = [table['header']] + table['rows'] if (
        table['header'] or table['rows'] or table['final_newline']) else []
    eol = table['line_ending']
    text = eol.join('|'.join(cells) for cells in lines)
    if table['final_newline']:
        text += eol
    return (_BOM if table['bom'] else '') + text


def tables_from_bundle(bundle: dict) -> dict[str, str]:
    """{relative path: CSV text} for every table in the bundle. Write each
    with `newline=''` and UTF-8 to get the original bytes back."""
    return {path: table_text(table) for path, table in bundle['tables'].items()}


def _read_table(project_dir: str, rel: str, kind: str,
                warnings: list[str]) -> dict | None:
    """The table at `rel`, or None with a warning saying why it isn't."""
    path = os.path.join(project_dir, rel)
    try:
        with open(path, 'rb') as f:
            raw = f.read()
    except OSError as e:
        warnings.append(f'{rel}: could not be read ({e.strerror or e}); '
                        f'it is not in the bundle')
        return None
    try:
        text = raw.decode('utf-8')
    except UnicodeDecodeError as e:
        warnings.append(f'{rel}: not UTF-8 (byte {e.start}); it is not in the '
                        f'bundle')
        return None
    table = parse_table(text)
    if table_text(table).encode('utf-8') != raw:  # parse_table's guarantee
        raise RuntimeError(f'export: {rel} does not round-trip; this is a bug')
    if table['line_ending'] == '\n' and '\r' in text:
        warnings.append(f'{rel}: mixed line endings; rows are split on LF and '
                        f'each CR stays at the end of its line\'s last cell')
    elif '\r' in text.replace('\r\n', ''):
        warnings.append(f'{rel}: a CR that doesn\'t end a line; rows are split on '
                        f'CRLF and the stray CR stays inside its cell')
    table['kind'] = kind
    return table


def _rel(project_dir: str, path: str) -> str:
    return os.path.relpath(path, project_dir).replace(os.sep, '/')


def _csvs(directory: str, prefix: str = '') -> list[str]:
    """The `prefix*.csv` files in `directory`, sorted. Listed, not globbed: a
    project path may hold glob characters (`[draft]`)."""
    try:
        names = os.listdir(directory)
    except (FileNotFoundError, NotADirectoryError):
        return []
    return sorted(os.path.join(directory, n) for n in names
                  if n.startswith(prefix) and n.endswith('.csv')
                  and os.path.isfile(os.path.join(directory, n)))


def _score_tables(project_dir: str, warnings: list[str]) -> tuple[str | None, list[str]]:
    """The latest complete score cycle (relative) and the score CSVs to carry."""
    from storyforge.project import latest_scores
    paths = []
    cycle = latest_scores(project_dir)
    cycle_rel = None
    if cycle:
        real_project = os.path.realpath(project_dir)
        real_cycle = os.path.realpath(cycle)
        if os.path.commonpath([real_project, real_cycle]) != real_project:
            warnings.append(f'working/scores/latest points outside the project '
                            f'({real_cycle}); the score cycle is not in the bundle')
        else:
            cycle_rel = _rel(real_project, real_cycle)
            paths += [os.path.join(project_dir, cycle_rel, os.path.basename(p))
                      for p in _csvs(real_cycle)]
    structural = os.path.join(project_dir, 'working', 'scores', 'structural-latest.csv')
    if os.path.isfile(structural):
        paths.append(structural)
    return cycle_rel, paths


def _audit_paths(project_dir: str, warnings: list[str]) -> list[str]:
    """PROVISIONAL: working/audit*.csv and every CSV under working/audit/."""
    working = os.path.join(project_dir, 'working')
    paths = _csvs(working, 'audit')
    audit_dir = os.path.join(working, 'audit')
    for root, dirs, files in os.walk(audit_dir):
        dirs.sort()
        for name in sorted(files):
            path = os.path.join(root, name)
            if name.endswith('.csv'):
                paths.append(path)
            elif name != '.gitkeep':
                warnings.append(f'{_rel(project_dir, path)}: not a CSV; the '
                                f'bundle carries only the audit log\'s CSVs')
    return paths


def _collect_tables(project_dir: str, warnings: list[str]) -> tuple[str | None, dict]:
    sources: list[tuple[str, str]] = []
    sources += [(p, 'reference') for p in
                _csvs(os.path.join(project_dir, 'reference'))]
    score_cycle, score_paths = _score_tables(project_dir, warnings)
    sources += [(p, 'scores') for p in score_paths]
    sources += [(p, 'timeline') for p in
                _csvs(os.path.join(project_dir, 'working'), 'timeline')]
    sources += [(p, 'audit') for p in _audit_paths(project_dir, warnings)]

    tables = {}
    for path, kind in sources:
        rel = _rel(project_dir, path)
        table = _read_table(project_dir, rel, kind, warnings)
        if table is not None:
            tables[rel] = table
    return score_cycle, tables


# ============================================================================
# Bundle
# ============================================================================

def storyforge_version(warnings: list[str]) -> str:
    """The plugin version from .claude-plugin/plugin.json; '' with a warning
    when it can't be read."""
    path = os.path.join(get_plugin_dir(), '.claude-plugin', 'plugin.json')
    try:
        with open(path, encoding='utf-8') as f:
            version = json.load(f).get('version', '')
    except (OSError, ValueError, AttributeError) as e:
        warnings.append(f'the Storyforge version could not be read from {path} '
                        f'({e}); storyforge_version is empty')
        return ''
    return str(version)


def _project(project_dir: str) -> dict[str, str]:
    title = (read_yaml_field('project.title', project_dir)
             or read_yaml_field('title', project_dir))
    genre = (read_yaml_field('project.genre', project_dir)
             or read_yaml_field('genre', project_dir))
    return {
        'title': title,
        'genre': genre,
        'medium': get_medium(project_dir),
        'phase': read_yaml_field('phase', project_dir),
    }


def build_bundle(project_dir: str, strict_dashboard: bool = False) -> dict:
    """The export bundle for the project at `project_dir`. No API calls.

    `strict_dashboard`: raise when `dashboard_data` can't be built, instead of
    leaving it null with a warning. `publish` passes it: Bookshelf reads the
    bundle's `dashboard_data`, and a book published without it would quietly
    lose its dashboard.

    Raises:
        ledger.NotMigratedError: knowledge.csv or physical-states.csv is still
            in reference/ (run `storyforge migrate`).
        ledger.LedgerError: commitments.csv can't be read as it is.
        Exception: whatever stopped `dashboard_data`, with `strict_dashboard`.
    """
    ledger.load(project_dir)  # refuse an unmigrated or malformed ledger first
    warnings: list[str] = []
    version = storyforge_version(warnings)
    score_cycle, tables = _collect_tables(project_dir, warnings)

    from storyforge.visualize import load_dashboard_data
    try:
        dashboard = load_dashboard_data(project_dir)
    except ledger.LedgerError:
        raise
    except Exception as e:  # named in the bundle, never dropped silently
        if strict_dashboard:
            raise
        warnings.append(f'dashboard_data could not be built ({type(e).__name__}: '
                        f'{e}); it is null in the bundle')
        dashboard = None

    return {
        'schema_version': SCHEMA_VERSION,
        'storyforge_version': version,
        'project': _project(project_dir),
        'score_cycle': score_cycle,
        'tables': tables,
        'dashboard_data': dashboard,
        'warnings': warnings,
    }


def dumps(bundle: dict) -> str:
    """The bundle as stable JSON: sorted keys, UTF-8 characters kept, LF."""
    return json.dumps(bundle, ensure_ascii=False, sort_keys=True, indent=1) + '\n'


def write_bundle(bundle: dict, path: str) -> None:
    """Write the bundle to `path` (UTF-8, LF), creating its directory.

    Atomic: written to a temporary file beside `path`, then moved over it, so
    a reader never sees half a bundle. Raises OSError when it can't write.
    """
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix='.bundle-', suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as f:
            f.write(dumps(bundle))
        umask = os.umask(0)
        os.umask(umask)
        os.chmod(tmp, 0o666 & ~umask)  # mkstemp's 0600 would outlive the move
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.remove(tmp)
        raise


def build_bundle_quietly(project_dir: str) -> dict:
    """`build_bundle` with anything its readers print sent to stderr, so the
    bundle can go to stdout."""
    with contextlib.redirect_stdout(sys.stderr):
        return build_bundle(project_dir)
