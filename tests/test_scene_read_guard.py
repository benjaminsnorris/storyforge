"""No new raw read of a scene file (#610's review, T-2/TD-1).

Scene prose that feeds analysis, scoring, word counts or a prompt comes from
`illustrations.read_scene_prose`, which strips illustration markers (#280);
code that needs the markers or the exact bytes reads through
`illustrations.read_scene_raw`, or opens the file itself and is listed in
RAW_READS below with why. This test walks every module's functions and fails
on any other `open()` (or `read_text` / `read_text_noting` / `_read_file`) of a
path built from `scenes` — so the next scene reader has to choose.

It is a static check, so it can miss a read whose path arrives from far away
(a parameter with an unrelated name); it errs that way rather than flagging
reads of other files.
"""

import ast
import os
import re

import pytest

PKG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   'scripts', 'lib', 'python', 'storyforge')

#: Parameter and variable names that hold a scene file path wherever they occur.
_SCENE_PATH_NAME = re.compile(
    r'^(sf|sf_path|scene_file|scene_path|scene_md|prose_path|draft_path|prev_file|'
    r'scenes_dir|scenes_src|scene_dir|fpath|filepath)$')
_READERS = {'open', 'read_text', 'read_text_noting', '_read_file'}

#: The deliberate raw reads: (module, function) → why the markers or the
#: exact bytes are needed. Graphic-novel modules are listed whole: `illustrate`
#: refuses a GN project, so its scenes carry no markers.
RAW_READS = {
    ('illustrations.py', 'read_scene_raw'): 'the raw reader',
    ('illustrations.py', 'validate_plan'): 'the marker validator reads the markers',
    ('cmd_illustrate.py', 'run_embed'): 'writes markers into the scene',
    ('cmd_illustrate.py', '_unembed_superseded'): 'removes markers from the scene',
    ('cmd_illustrate.py', '_scene_split'): 'splits at the marker\'s reading position '
                                           '(illustrations.reading_position strips)',
    ('assembly.py', 'extract_scene_prose'): 'assembly renders the markers',
    ('assembly.py', 'read_matter_file'): 'front and back matter, not a scene (a '
                                         '`filepath` the name match cannot tell apart)',
    ('assembly.py', 'generate_publish_manifest'): 'turns markers into the manifest\'s '
                                                  'illustrations list, then strips',
    ('cmd_cleanup.py', '_scene_files_to_clean'): 'writes the cleaned scene back',
    ('cmd_cleanup.py', '_check_scene_artifacts'): 'reports what the clean would change '
                                                  'in the file as written',
    ('cmd_enrich.py', 'main'): 'a title from the first `#` line; a marker is never one',
    ('cmd_revise.py', '_restore_gate_markers'): 'restores markers into the file',
    ('cmd_revise.py', '_scene_texts'): 'detects which scenes a pass changed, '
                                       'markers included',
    ('cmd_write.py', '_gate_drafted_scene'): 'the gate fixes the file by find/replace '
                                             '(the gate exception, docs/history.md)',
    ('cmd_write.py', '_interactive_problem'): 'compares the file to what was there; '
                                              'its floor counts prose',
    ('cmd_write.py', '_keep_cli_markers'): 'restores markers into the file the CLI wrote',
    ('cmd_write.py', '_run_direct_mode'): 'the scene before the CLI rewrote it, whose '
                                          'markers it keeps',
    ('gate.py', 'snapshot'): 'byte comparison: the book before this run',
    ('gate.py', '_unchanged_since'): 'byte comparison against the snapshot',
    ('gate.py', '_gate_scene'): 'the gate exception: it fixes the file by find/replace',
    ('gate.py', '_scene_sha'): 'byte digest of the file',
    ('gate.py', 'accept_blocked'): 'matches recorded quotes against the file',
    ('parsing.py', '_write_scene'): 'the scene a reply overwrites, whose markers it keeps',
    ('source.py', 'plan_import'): 'imports source files into scenes/',
    ('source.py', 'source_prose'): 'source files, not scenes',
}
_GN_MODULES = {'cmd_evaluate_gn.py', 'cmd_revise_gn.py', 'cmd_score_gn.py',
               'cmd_script_package.py', 'cmd_write_gn.py', 'cmd_extract_gn.py'}


def _mentions_scenes(node: ast.AST, tainted: set[str]) -> bool:
    for n in ast.walk(node):
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and (
                n.value == 'scenes' or n.value.startswith('scenes/')):
            return True
        if isinstance(n, ast.Name) and (n.id in tainted or _SCENE_PATH_NAME.match(n.id)):
            return True
    return False


def _builds_a_path(value: ast.AST) -> bool:
    """A path expression (`os.path.join(...)`, a name, an f-string), not any
    call that happens to take a scene path (a prompt builder's result is not
    a path)."""
    if isinstance(value, ast.Call):
        return getattr(value.func, 'attr', getattr(value.func, 'id', '')) == 'join'
    return isinstance(value, (ast.Name, ast.JoinedStr, ast.Constant, ast.BinOp))


def _writes(call: ast.Call) -> bool:
    modes = call.args[1:2] + [k.value for k in call.keywords if k.arg == 'mode']
    return any(isinstance(m, ast.Constant) and isinstance(m.value, str)
               and set(m.value) & set('wax') for m in modes)


def _own_nodes(fn: ast.AST):
    """*fn*'s nodes, not those of a function nested in it."""
    stack = list(ast.iter_child_nodes(fn))
    while stack:
        n = stack.pop()
        yield n
        if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            stack.extend(ast.iter_child_nodes(n))


def raw_scene_reads(path: str) -> list[tuple[str, int]]:
    """(function, line) of each raw read of a scene path in the module."""
    tree = ast.parse(open(path, encoding='utf-8').read())
    hits = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        nodes = list(_own_nodes(fn))
        tainted: set[str] = set()
        grew = True
        while grew:   # names assigned from a scene path, to a fixed point
            grew = False
            for n in nodes:
                if (isinstance(n, ast.Assign) and _builds_a_path(n.value)
                        and _mentions_scenes(n.value, tainted)):
                    for t in n.targets:
                        if isinstance(t, ast.Name) and t.id not in tainted:
                            tainted.add(t.id)
                            grew = True
        for n in nodes:
            if not isinstance(n, ast.Call) or not n.args:
                continue
            f = n.func
            name = f.id if isinstance(f, ast.Name) else getattr(f, 'attr', '')
            if name in _READERS and not _writes(n) and _mentions_scenes(n.args[0], tainted):
                hits.append((fn.name, n.lineno))
    return hits


def _all_reads():
    out = {}
    for name in sorted(os.listdir(PKG)):
        if name.endswith('.py') and name not in _GN_MODULES:
            for func, line in raw_scene_reads(os.path.join(PKG, name)):
                out.setdefault((name, func), []).append(line)
    return out


def test_no_unlisted_raw_scene_read():
    unlisted = {k: v for k, v in _all_reads().items() if k not in RAW_READS}
    assert unlisted == {}, (
        'raw read of a scene file: read it through illustrations.read_scene_prose '
        '(analysis, scoring, word counts, prompts) or read_scene_raw (markers or '
        'exact bytes needed), or list it in RAW_READS with why')


def test_every_listed_raw_read_still_exists():
    """A stale entry would let a new raw read in under its name."""
    found = _all_reads()
    assert [k for k in RAW_READS if k not in found] == []


@pytest.mark.parametrize('src', [
    "def f(project_dir, sid):\n    with open(os.path.join(project_dir, 'scenes', sid)) as h:\n"
    "        return h.read()\n",
    "def f(d, sid):\n    path = os.path.join(d, 'scenes', f'{sid}.md')\n    return open(path).read()\n",
    "def f(scenes_dir, sid):\n    p = os.path.join(scenes_dir, sid)\n    t = read_text(p)\n",
    "def f(scene_file):\n    return open(scene_file, encoding='utf-8').read()\n",
])
def test_the_guard_catches_a_raw_read(tmp_path, src):
    path = tmp_path / 'm.py'
    path.write_text('import os\n' + src)
    assert [f for f, _ in raw_scene_reads(str(path))] == ['f']


def test_the_guard_ignores_writes_and_other_files(tmp_path):
    path = tmp_path / 'm.py'
    path.write_text("import os\n"
                    "def f(project_dir, sid, text):\n"
                    "    with open(os.path.join(project_dir, 'scenes', sid), 'w') as h:\n"
                    "        h.write(text)\n"
                    "    return open(os.path.join(project_dir, 'reference', 'x.csv')).read()\n")
    assert raw_scene_reads(str(path)) == []
