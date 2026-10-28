"""Annotations must not name a module-level type before it is defined.

Before Python 3.14, the annotations on a module-level function or method are
evaluated when the ``def`` runs. A name defined further down the module raises
NameError at import time, so the whole module (and every command importing it)
fails on 3.10-3.13 while working on 3.14, where evaluation is deferred. This
check is static so it catches the mistake on any interpreter.
"""

import ast
import builtins
import os

import pytest

_PKG_DIR = os.path.normpath(os.path.join(
    os.path.dirname(__file__), os.pardir, os.pardir,
    'scripts', 'lib', 'python', 'storyforge',
))
ALL_MODULES = sorted(f[:-3] for f in os.listdir(_PKG_DIR)
                     if f.endswith('.py') and f != '__init__.py')


def _defined_at(tree):
    """Line on which each module-level name is first bound."""
    first = {}

    def bind(name, line):
        first.setdefault(name, line)

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bind(node.name, node.lineno)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                bind((alias.asname or alias.name).split('.')[0], node.lineno)
        else:
            for sub in ast.walk(node):
                if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Store):
                    bind(sub.id, node.lineno)
    return first


def _eager_annotations(tree):
    """(line, annotation) pairs evaluated while the module is imported."""
    if any(isinstance(n, ast.ImportFrom) and n.module == '__future__'
           and any(a.name == 'annotations' for a in n.names) for n in tree.body):
        return
    funcs = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            funcs.append((node.lineno, node))
        elif isinstance(node, ast.ClassDef):
            funcs += [(node.lineno, f) for f in node.body
                      if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))]
    for line, func in funcs:
        args = func.args
        for arg in args.posonlyargs + args.args + args.kwonlyargs + [args.vararg, args.kwarg]:
            if arg is not None and arg.annotation is not None:
                yield line, arg.annotation
        if func.returns is not None:
            yield line, func.returns


@pytest.mark.parametrize('module_name', ALL_MODULES)
def test_annotations_name_only_defined_types(module_name):
    with open(os.path.join(_PKG_DIR, f'{module_name}.py'), encoding='utf-8') as f:
        tree = ast.parse(f.read())
    defined = _defined_at(tree)
    late = sorted({
        (line, sub.id)
        for line, annotation in _eager_annotations(tree)
        for sub in ast.walk(annotation)
        if isinstance(sub, ast.Name) and not hasattr(builtins, sub.id)
        and defined.get(sub.id, 0) > line
    })
    assert not late, (
        f'{module_name}.py annotates with names defined later '
        f'(NameError before Python 3.14): {late}; quote them')


def test_python_floor_message():
    from storyforge.__main__ import python_too_old
    assert python_too_old((3, 9, 6)) == (
        'Storyforge needs Python 3.10 or newer; this is Python 3.9.6 '
        '(the python3 first on PATH).')
    assert python_too_old((3, 10, 0)) is None
    assert python_too_old((3, 14, 1)) is None
