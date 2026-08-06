"""An independent reader for the YAML *we emit*, for tests to verify against.

One copy, deliberately shared by `tests/test_yaml_helpers.py` and
`tests/integration/test_assembly.py`. There were two near-identical private
copies (`parse_flat_metadata` and `_parsed`); the property that matters is
independence from `common.parse_yaml_scalar` — the function under test, which
must not be allowed to agree with itself — and that property is about *what this
is independent of*, not about how many copies exist. Two copies just meant a
correction had to land twice, which is how both of them came to share the same
blind spot (below).

Not pyyaml: it is installed on no declared dependency list, and the repo's YAML
handling is deliberately dependency-free.

**It rejects an unescaped apostrophe, and that is the whole point.** Both earlier
copies checked only `raw.startswith("'") and raw.endswith("'")` — a first-and-
last-character test, which is precisely the mistake
`common._parse_quoted_scalar`'s docstring says the three pre-#277 parsers made.
It cannot see #277's actual crash: `author: 'Flannery O'Connor'` and
`author: 'Flannery O''Connor'` both satisfy it and both reduce to the same value,
so every metadata test passed with the escaping fix reverted, while pandoc exits
64 on the first. It also accepted `subject: 'a'b'`, `subject: '` and
`subject: 'x' y'`, all three of which `yaml.safe_load` rejects.
"""


def parse_emitted_yaml_metadata(metadata: str) -> dict[str, str]:
    """Parse a generated single-quoted YAML block into `{key: value}`.

    Raises `AssertionError` — naming the offending line — if a value is not
    single-quoted, or carries an apostrophe that is not doubled.
    """
    out: dict[str, str] = {}
    for line in metadata.split('\n'):
        if line.strip() in ('---', ''):
            continue
        key, sep, raw = line.partition(': ')
        assert sep, f'not a `key: value` line: {line!r}'
        raw = raw.strip()
        # `len(raw) >= 2` is load-bearing: a lone `'` starts and ends with a
        # quote, so without it a single stray quote reads as an empty value.
        assert len(raw) >= 2 and raw.startswith("'") and raw.endswith("'"), (
            f'every emitted value must be single-quoted, got {line!r}')
        inner = raw[1:-1]
        i = 0
        while i < len(inner):
            if inner[i] == "'":
                assert inner[i + 1:i + 2] == "'", (
                    f'unescaped apostrophe at offset {i} of {raw!r} — a '
                    f'single-quoted YAML scalar spells one by doubling it, and '
                    f'a lone one closes the string early. pandoc exits 64 on '
                    f'this (#277).')
                i += 2
                continue
            i += 1
        out[key.strip()] = inner.replace("''", "'")
    return out
