"""The visual-state transition log.

A row records the moment a tracked entity's visible state *changes*; the state
persists forward until the next transition for that entity. The state at any
scene is a forward walk over the log.

This exists because the illustration flow already had `reference/canon/` for
what must **never** change — a character's face, a lamp's construction — and
nowhere to put what changes *on schedule*: wardrobe by chapter, a lamp lit or
dark, how many village lights are still burning. Four of ten real findings on a
real book traced to that gap.

Sparse rather than a dense scene x entity grid because scene-map operations
insert, merge, split, and reorder — a transition keyed "from act2-sc01 onward"
still means something after a scene lands before it, where a dense grid would
have no row and fall silently blank. And one authorial decision ("from Chapter 4
they arrive dressed") is recorded once instead of restated in every illustrated
scene from 4 to 15, each restatement a cell that can go stale alone.

The trade sparse makes: a row can name a scene that has since been cut, which is
why `state_unknown_scene` is an error and not a warning.

Granularity is one track per independently-changing aspect, not one per entity:
`nora-clothing` rather than `nora`, because clothing and injury change on
different schedules and a single track would force restating one to change the
other. The convention is `{canon_id}-{aspect}` where an entity has several
tracks and a bare `canon_id` where it has one.

See benjaminsnorris/storyforge#278 and the spec at
docs/superpowers/specs/2026-07-28-illustration-state-matrix-and-packet-design.md.
"""

import csv
import os
from typing import TypedDict

from storyforge.common import log

STATE_COLUMNS: list[str] = ['entity', 'from_scene', 'state', 'evidence']
STATE_FILENAME = 'visual-state.csv'
STATE_FILE = os.path.join('reference', STATE_FILENAME)


class Transition(TypedDict):
    """One row of the log: an entity's visible state, from a scene onward."""
    entity: str
    from_scene: str
    state: str
    evidence: str


def state_path(project_dir: str) -> str:
    """Absolute path to the transition log, whether or not it exists."""
    return os.path.join(project_dir, STATE_FILE)


def read_transitions(project_dir: str) -> list[Transition]:
    """Every transition, in file order. An absent file is empty, not an error.

    A row with no `entity` names nothing and is skipped — with a log line,
    because a silently dropped row is a state the author believes is recorded.
    """
    from storyforge.illustrations import _read_ref_csv
    rows = _read_ref_csv(project_dir, STATE_FILENAME)
    out: list[Transition] = []
    for index, row in enumerate(rows, start=2):  # +1 header, +1 for 1-based
        entity = (row.get('entity') or '').strip()
        if not entity:
            log(f'WARNING: {STATE_FILE} line {index} has no entity — skipped')
            continue
        out.append({
            'entity': entity,
            'from_scene': (row.get('from_scene') or '').strip(),
            'state': (row.get('state') or '').strip(),
            'evidence': (row.get('evidence') or '').strip(),
        })
    return out


def state_at(project_dir: str, scene_id: str) -> dict[str, str]:
    """Entity -> state in effect at *scene_id*.

    A transition takes effect **at** its own scene, so the comparison is `<=`.
    An entity whose first transition is later than *scene_id* is absent from the
    result rather than present-and-blank — "not yet established" and
    "established as empty" are different, and callers report them differently.

    `_scene_order` prefers the chapter map and falls back to `scenes.csv:seq`,
    so a scene the chapter map omits has no position and resolves to `{}`. That
    is the right degradation — nothing is guessed — but it reads identically to
    "nothing is tracked yet", so it gets a log line.
    """
    from storyforge.illustrations import _scene_order
    order = _scene_order(project_dir)
    if scene_id not in order:
        log(f'WARNING: scene {scene_id!r} has no reading position (absent from '
            f'the chapter map and from scenes.csv) — visual state resolves as '
            f'empty, not as unchanged')
        return {}
    target = order[scene_id]

    best: dict[str, tuple[int, str]] = {}
    for transition in read_transitions(project_dir):
        pos = order.get(transition['from_scene'])
        if pos is None or pos > target:
            continue
        prior = best.get(transition['entity'])
        # `>=` rather than `>`: two transitions for one entity at the same scene
        # means the later row in the file wins, which is deterministic and
        # matches how the plan CSV resolves duplicates.
        if prior is None or pos >= prior[0]:
            best[transition['entity']] = (pos, transition['state'])
    return {entity: state for entity, (_pos, state) in sorted(best.items())}


def entities(project_dir: str) -> list[str]:
    """Every distinct tracked entity, sorted."""
    return sorted({t['entity'] for t in read_transitions(project_dir)})


def write_transitions(project_dir: str, rows: list[Transition]) -> str:
    """Write the log and return its path.

    `lineterminator` is explicit because `csv.writer` emits its own terminator
    and defaults to CRLF — which `cleanup` flags, and which turns every
    one-field edit into a whole-file diff. `newline=''` on the open does not
    prevent it.
    """
    path = state_path(project_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=STATE_COLUMNS, delimiter='|',
                                lineterminator='\n')
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, '') for k in STATE_COLUMNS})
    return path
