"""storyforge init — scaffold a project without the interactive init skill.

Makes the layout `/storyforge:init` makes for a novel on the elaboration
pipeline (coaching level from the template, `full`): the `./storyforge`
runner, `.gitignore`, `storyforge.yaml`, `CLAUDE.md`, the reference templates
and `working/pipeline.csv`. Run it from the plugin, since a new directory has
no runner yet:

    $CLAUDE_PLUGIN_ROOT/storyforge init beowulf --meta beowulf.json --fetch

Details come from `--meta` (a `source fetch` config, whose descriptive keys
title, author, year, genre and logline it reads; the config is kept as
`reference/gutenberg.json`) or the flags, which win. `--fetch` then runs
`source fetch` (the manuscript from Project Gutenberg) and sets
`project.target_words` from it; `--manuscript FILE` copies a manuscript in
instead.

Git: a directory outside any repository becomes one, and the project is its
first commit on `main`. Inside a repository (a book repo's `source/`), the
project is committed on the current branch, or a new `storyforge/init-*`
branch when that is `main`. `--no-commit` writes and stops.

Usage:
    storyforge init DIR --title T [--author A] [--genre G] [--logline L]
                        [--year Y] [--target-words N] [--meta FILE]
                        [--fetch [--verse] [--input RAW]] [--manuscript FILE]
                        [--no-commit]
"""

import argparse
import os
import shutil
import subprocess
import sys

from storyforge.common import get_plugin_dir, install_signal_handlers, log

# Graphic-novel-only templates that a prose project does not get.
GN_ONLY = {'canon', 'visual-style.md'}

PIPELINE_HEADER = ('cycle|started|status|evaluation|scoring|plan|review|'
                   'recommendations|summary')

DIRS = ['reference', 'scenes', 'manuscript/press-kit',
        'working/logs', 'working/evaluations', 'working/plans']


class InitError(Exception):
    pass


def parse_args(argv):
    p = argparse.ArgumentParser(
        prog='storyforge init',
        description='Scaffold a Storyforge project (no questions asked).')
    p.add_argument('dir', help='The project directory (created; must be empty if it exists)')
    p.add_argument('--meta', help='A source-fetch JSON config; its title, author, '
                                  'year, genre and logline fill the project')
    p.add_argument('--title')
    p.add_argument('--author')
    p.add_argument('--genre')
    p.add_argument('--logline')
    p.add_argument('--year')
    p.add_argument('--target-words', type=int,
                   help='project.target_words (default: the manuscript, to the '
                        'nearest thousand; else the template)')
    src = p.add_mutually_exclusive_group()
    src.add_argument('--fetch', action='store_true',
                     help='Run `source fetch` with the config: manuscript.md from Gutenberg')
    src.add_argument('--manuscript', help='Copy this file in as manuscript.md')
    p.add_argument('--gutenberg', metavar='ID', help='With --fetch: the ebook number')
    mode = p.add_mutually_exclusive_group()
    mode.add_argument('--verse', dest='verse', action='store_true', default=None,
                      help='With --fetch: keep line breaks and stanzas')
    mode.add_argument('--prose', dest='verse', action='store_false',
                      help='With --fetch: one paragraph per line (the default)')
    p.add_argument('--input', help='With --fetch: read the raw text from this file')
    p.add_argument('--no-commit', action='store_true', help='Write, do not commit')
    args = p.parse_args(argv)
    if not args.fetch and (args.gutenberg or args.input or args.verse is not None):
        p.error('--gutenberg, --input, --verse and --prose go with --fetch')
    return args


def yaml_str(value) -> str:
    return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"') + '"'


def _details(args, meta: dict) -> dict:
    d = {k: meta.get(k) for k in ('title', 'author', 'year', 'genre', 'logline')}
    for k in d:
        if getattr(args, k) is not None:
            d[k] = getattr(args, k)
    if not d['title']:
        raise InitError('no title: pass --title (or a --meta with "title")')
    return d


def _storyforge_yaml(plugin: str, d: dict, target_words: int | None) -> str:
    with open(os.path.join(plugin, 'templates', 'storyforge.yaml')) as f:
        yaml = f.read()
    yaml = (yaml
            .replace('"PROJECT_TITLE"', yaml_str(d['title']))
            .replace('"PROJECT_GENRE"', yaml_str(d['genre'] or ''))
            .replace('"PROJECT_LOGLINE"', yaml_str(d['logline'] or '')))
    if target_words:
        yaml = yaml.replace('target_words: 80000', f'target_words: {target_words}')
    if d['author']:
        # publish and the cover read the author from production.author
        yaml += f'\nproduction:\n  author: {yaml_str(d["author"])}\n'
    return yaml


def _claude_md(d: dict, meta: dict) -> str:
    about = d['title']
    if d['author']:
        about += f' by {d["author"]}'
    if meta.get('translator'):
        about += f', translated by {meta["translator"]}'
    if d['year']:
        about += f' ({d["year"]})'
    lines = [f'# {d["title"]} — Storyforge Project', '', '## About This Project', '']
    if meta.get('gutenberg_id') is not None:
        lines.append(f'{about}, public domain via Project Gutenberg '
                     f'#{meta["gutenberg_id"]}. `reference/gutenberg.json` is how '
                     '`./storyforge source fetch` made `manuscript.md` from it.')
    else:
        lines.append(f'{about}.')
    if d['logline']:
        lines += ['', d['logline']]
    lines += [
        '', '## Working with Storyforge', '',
        '- `/storyforge:forge` — main hub, recommends what to work on next',
        '- `./storyforge scenes-setup --split-manuscript` — split `manuscript.md` into scenes',
        '- `./storyforge extract` — extract the scene data from existing prose',
        '- `./storyforge score`, `evaluate`, `revise`, `write` — craft scoring, '
        'evaluation, revision, drafting',
        '', '## Where to Find Things', '',
        '- `storyforge.yaml` — project configuration',
        '- `working/pipeline.csv` — pipeline history',
        '- `reference/` — scene metadata, registries and bibles',
        '- `scenes/` — scene prose files',
        '', '## Standing Instructions', '', '',
    ]
    return '\n'.join(lines)


def _in_git_repo(path: str) -> bool:
    r = subprocess.run(['git', 'rev-parse', '--is-inside-work-tree'], cwd=path,
                       capture_output=True, text=True)
    return r.returncode == 0 and r.stdout.strip() == 'true'


def main(argv=None):
    args = parse_args(argv if argv is not None else sys.argv[1:])
    install_signal_handlers()
    from storyforge import gutenberg

    project = os.path.abspath(args.dir)
    try:
        meta = gutenberg.read_config(args.meta) if args.meta else {}
        details = _details(args, meta)
        if os.path.exists(project) and (not os.path.isdir(project) or os.listdir(project)):
            raise InitError(f'{project} exists and is not empty')
        if args.manuscript and not os.path.isfile(args.manuscript):
            raise InitError(f'no manuscript at {args.manuscript}')
        if args.fetch and not args.meta:
            raise InitError('--fetch needs --meta (the config: chapter_heading at least)')
    except (InitError, gutenberg.GutenbergError) as e:
        log(f'ERROR: {e}')
        return 1

    plugin = get_plugin_dir()
    templates = os.path.join(plugin, 'templates')

    # Build the manuscript before writing anything, so a config that can't
    # make one leaves no half-made project behind
    fetched = None
    if args.fetch:
        from storyforge.cmd_source import fetch_config
        try:
            fetch_meta = fetch_config(project, args.meta, args.gutenberg, args.verse)
            fetched = gutenberg.build(project, fetch_meta, input_path=args.input)
        except gutenberg.GutenbergError as e:
            log(f'ERROR: {e}')
            log('Nothing was written.')
            return 1

    words = None
    if fetched:
        words = fetched.stats['words']
    elif args.manuscript:
        with open(args.manuscript, encoding='utf-8') as f:
            words = len(f.read().split())
    target = args.target_words or (max(1000, round(words, -3)) if words else None)

    for sub in DIRS:
        os.makedirs(os.path.join(project, sub), exist_ok=True)
    runner = os.path.join(project, 'storyforge')
    shutil.copy(os.path.join(templates, 'storyforge-runner.sh'), runner)
    os.chmod(runner, 0o755)
    shutil.copy(os.path.join(templates, 'gitignore'), os.path.join(project, '.gitignore'))
    ref_templates = os.path.join(templates, 'reference')
    for name in sorted(os.listdir(ref_templates)):
        entry = os.path.join(ref_templates, name)
        if name not in GN_ONLY and os.path.isfile(entry):
            with open(entry, encoding='utf-8') as f:
                text = f.read()
            with open(os.path.join(project, 'reference', name), 'w', encoding='utf-8') as f:
                f.write(text.replace('PROJECT_TITLE', details['title']))
    with open(os.path.join(project, 'storyforge.yaml'), 'w') as f:
        f.write(_storyforge_yaml(plugin, details, target))
    with open(os.path.join(project, 'CLAUDE.md'), 'w') as f:
        f.write(_claude_md(details, fetched.meta if fetched else meta))
    with open(os.path.join(project, 'working', 'pipeline.csv'), 'w') as f:
        f.write(PIPELINE_HEADER + '\n')

    if fetched:
        gutenberg.write_files(project, gutenberg.plan_writes(project, fetched))
        log(f'Manuscript from Gutenberg #{fetched.meta.get("gutenberg_id", "?")} '
            f'({"verse" if fetched.meta.get("verse") else "prose"}): '
            f'{gutenberg.describe(fetched.stats)}')
    else:
        if meta:
            with open(os.path.join(project, gutenberg.CONFIG_REL), 'w') as f:
                f.write(gutenberg.config_text(meta))
        if args.manuscript:
            shutil.copy(args.manuscript, os.path.join(project, 'manuscript.md'))

    log(f'Created {project}' + (f' ({words} words)' if words else ''))
    if args.no_commit:
        log('Written, not committed (--no-commit).')
        return 0
    return _commit(project, details['title'])


def _written(project: str) -> list[str]:
    """Every file the scaffold wrote, relative to the project (it began
    empty), for a commit that takes only these."""
    out = []
    for root, dirs, files in os.walk(project):
        dirs[:] = [d for d in dirs if d != '.git']
        out += [os.path.relpath(os.path.join(root, f), project) for f in files]
    return sorted(out)


def _commit(project: str, title: str) -> int:
    message = f'Initialize Storyforge project: {title}'
    if not _in_git_repo(project):
        # A new repository: the project is its first commit, on main, as the
        # init skill does
        for cmd in (['git', 'init', '-q', '-b', 'main'], ['git', 'add', '-A'],
                    ['git', 'commit', '-q', '-m', message]):
            r = subprocess.run(cmd, cwd=project, capture_output=True, text=True)
            if r.returncode != 0:
                log(f'ERROR: {" ".join(cmd)} failed: {(r.stderr or r.stdout).strip()}')
                return 1
        log(f'Committed on main in a new repository. Next: cd {project} && '
            './storyforge scenes-setup --split-manuscript')
        return 0
    from storyforge.git import commit_and_push, ensure_on_branch
    ensure_on_branch('init', project)
    # Only what init wrote: anything the author had staged elsewhere in the
    # repo stays staged and out of this commit
    if not commit_and_push(project, message, _written(project)):
        log('ERROR: the project is written but the commit failed; commit it yourself')
        return 1
    log(f'Next: cd {project} && ./storyforge scenes-setup --split-manuscript')
    return 0
