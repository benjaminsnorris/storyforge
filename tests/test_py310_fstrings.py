"""Python 3.10 compatibility: no backslash inside an f-string expression.

Python 3.12 allows `f"{x or 'it\\'s'}"`; 3.10, which the E7 CI runs, is a
SyntaxError at import (timeline.py and extract_describe.py, 2026-11-03: the
3.10 job failed on main from #488 on). This scans the package with the 3.12+
tokenizer, which marks where an f-string's expressions are.
"""

import pathlib
import sys
import tokenize

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _offenders(path):
    found, depth = [], 0
    with open(path, 'rb') as f:
        for tok in tokenize.tokenize(f.readline):
            if tok.type == tokenize.FSTRING_START:
                depth += 1
            elif tok.type == tokenize.FSTRING_END:
                depth -= 1
            elif depth and tok.type != tokenize.FSTRING_MIDDLE and '\\' in tok.string:
                found.append(f'{path.relative_to(ROOT)}:{tok.start[0]}')
    return found


@pytest.mark.skipif(sys.version_info < (3, 12), reason='needs the 3.12 f-string tokenizer')
def test_no_backslash_in_an_fstring_expression():
    files = sorted((ROOT / 'scripts').rglob('*.py')) + sorted((ROOT / 'evals').rglob('*.py'))
    offenders = [o for p in files for o in _offenders(p)]
    assert not offenders, 'backslash in an f-string expression (a 3.10 SyntaxError): ' \
        + ', '.join(offenders)
