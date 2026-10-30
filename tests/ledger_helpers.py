"""Write knowledge facts and physical states into a test project's ledger.

Tests used to write `knowledge.csv` / `physical-states.csv` text; the ledger
(`reference/commitments.csv`) replaced both. `write_facts` takes that same
old-file text and stores its rows as the ledger's facts of that type,
replacing the type's rows and keeping every other fact. Values are stored as
given (a physical `character` stays the name it was written as), so a test
keeps checking what it checked before.
"""

import os

from storyforge import ledger

_TYPE_OF = {'knowledge.csv': 'knowledge', 'physical-states.csv': 'physical'}


def write_facts(ref_dir, filename: str, text: str) -> None:
    """Replace the ledger's facts of `filename`'s type with `text`'s rows."""
    lines = [line for line in text.splitlines() if line.strip()]
    header = [h.strip() for h in lines[0].split('|')]
    rows = [dict(zip(header, line.split('|'))) for line in lines[1:]]
    ref_dir = str(ref_dir)
    os.makedirs(ref_dir, exist_ok=True)
    ledger.write_view(ref_dir, _TYPE_OF[filename], rows, origin='author',
                      introduced_by='author')
    if not rows and not os.path.isfile(os.path.join(ref_dir, ledger.LEDGER_FILE)):
        ledger.save_to(ref_dir, [], command='test')


def read_facts(ref_dir, filename: str) -> dict:
    """id → old-file-shaped row of `filename`'s type."""
    return ledger.view_map(str(ref_dir), _TYPE_OF[filename])
