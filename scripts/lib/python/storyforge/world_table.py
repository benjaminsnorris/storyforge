"""The world table: directions, light and distances, for checks that need
the book's geography and sky (#647; shared with #648's continuity checks:
geography and sky, and travel).

`reference/world.csv`, pipe-delimited, one fact a row::

    kind|name|value|note
    direction|the Tor|west|seen from the village
    sun|dawn|east|
    sight|face|30|metres at which a face can be made out
    distance|the wall > the ships|2000|metres
    speed|on foot|40000|metres a day

Kinds (`KINDS`):

- `direction`: a landmark and the compass direction it lies in from the
  book's usual standpoint (`value` a `COMPASS` word). "The sun set behind
  the Tor" puts the sun where the Tor is.
- `sun`: a time of day and where the sun is then (`value` a `COMPASS` word,
  or `none` when it's down). A row replaces the default for that time only
  (`DEFAULT_SUN`, a northern temperate sky): a book under another sky gives
  every time it uses.
- `sight`: a detail and the farthest it can be made out, in metres
  (`value` a positive number): `face` (a face, eyes, an expression) and
  `figure` (who someone is by build and bearing). Replaces `DEFAULT_SIGHT`.
- `distance`: two places, `A > B` (either order matches), and the metres
  between them.
- `speed` (#648): a way of travelling (`on foot`, `horse`, `ship`) and the
  farthest it goes in a day, in metres. The travel check holds a journey
  to the fastest the table gives (`fastest`); with no `speed` row it
  doesn't check travel, and says so.

The file is optional: without it the defaults apply. `load(project_dir)`
raises `WorldTableError` on a file it can't use (a bad header or row),
rather than checking against part of it; `problems(path)` lists what's wrong
for `storyforge cleanup`, which reports and never repairs.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

WORLD_FILE = 'world.csv'
COLUMNS = ('kind', 'name', 'value', 'note')
KINDS = ('direction', 'sun', 'sight', 'distance', 'speed')

#: Compass words and their bearings in degrees
COMPASS = {
    'north': 0, 'northeast': 45, 'east': 90, 'southeast': 135,
    'south': 180, 'southwest': 225, 'west': 270, 'northwest': 315,
}
_SHORT = {'n': 'north', 'ne': 'northeast', 'e': 'east', 'se': 'southeast',
          's': 'south', 'sw': 'southwest', 'w': 'west', 'nw': 'northwest'}
#: The sun's value when it is down
SUN_DOWN = 'none'

#: Where the sun is at each time of day, unless the table says otherwise
DEFAULT_SUN = {
    'dawn': 'east', 'sunrise': 'east', 'morning': 'east',
    'noon': 'south', 'midday': 'south', 'afternoon': 'southwest',
    'evening': 'west', 'sunset': 'west', 'dusk': 'west',
    'night': SUN_DOWN, 'midnight': SUN_DOWN,
}
#: The farthest, in metres, each detail can be made out
DEFAULT_SIGHT = {'face': 30.0, 'figure': 300.0}


class WorldTableError(ValueError):
    """`reference/world.csv` can't be used; the message names the file and row."""


def _key(text: str) -> str:
    return ' '.join(re.sub(r"[^\w\s'-]", ' ', (text or '').lower()).split())


def compass(word: str) -> str | None:
    """The `COMPASS` word `word` names ('NE', 'north-east', 'North East'), or None."""
    w = re.sub(r'[\s-]+', '', (word or '').strip().lower())
    w = _SHORT.get(w, w)
    return w if w in COMPASS else None


def angle(a: str, b: str) -> int:
    """Degrees between two compass words (0 to 180)."""
    d = abs(COMPASS[a] - COMPASS[b]) % 360
    return min(d, 360 - d)


def opposite(word: str) -> str:
    bearing = (COMPASS[word] + 180) % 360
    return next(k for k, v in COMPASS.items() if v == bearing)


def _number(text: str) -> float | None:
    try:
        n = float((text or '').strip())
    except ValueError:
        return None
    return n if n > 0 and n == n and n != float('inf') else None


def _pair(name: str) -> tuple[str, str] | None:
    parts = [_key(x) for x in (name or '').split('>')]
    return (parts[0], parts[1]) if len(parts) == 2 and all(parts) else None


@dataclass
class World:
    directions: dict[str, str] = field(default_factory=dict)
    sun_at: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_SUN))
    sight_m: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_SIGHT))
    distances: dict[frozenset, float] = field(default_factory=dict)
    speeds: dict[str, float] = field(default_factory=dict)

    def direction(self, where: str) -> str | None:
        """A compass word for `where`: a compass word itself, or a landmark
        the table names (a whole-word match inside a longer phrase counts:
        "behind the Tor" is the Tor)."""
        c = compass(where)
        if c:
            return c
        key = _key(where)
        if key in self.directions:
            return self.directions[key]
        for name in sorted(self.directions, key=len, reverse=True):
            if re.search(rf'(?<!\w){re.escape(name)}(?!\w)', key):
                return self.directions[name]
        return None

    def sun(self, time_of_day: str) -> str | None:
        """Where the sun is at `time_of_day` (a compass word or `SUN_DOWN`),
        or None when the time isn't one the table knows ("early dawn" is
        dawn: the longest time named inside it wins)."""
        key = _key(time_of_day)
        if not key:
            return None
        if key in self.sun_at:
            return self.sun_at[key]
        for name in sorted(self.sun_at, key=len, reverse=True):
            if re.search(rf'(?<!\w){re.escape(name)}(?!\w)', key):
                return self.sun_at[name]
        return None

    def sight(self, detail: str) -> float | None:
        return self.sight_m.get(_key(detail))

    def distance(self, a: str, b: str) -> float | None:
        """The metres between two places: a row naming both, or whose two
        names each stand as whole words inside one of them ("on the wall"
        and "by the ships" are `the wall > the ships`); the longest names
        win. None when no row does."""
        x, y = _key(a), _key(b)
        exact = self.distances.get(frozenset((x, y)))
        if exact is not None or not (x and y):
            return exact

        def inside(name: str, text: str) -> bool:
            return bool(re.search(rf'(?<!\w){re.escape(name)}(?!\w)', text))
        best: tuple[int, float] | None = None
        for pair, metres in self.distances.items():
            p, q = (tuple(pair) * 2)[:2]
            if (inside(p, x) and inside(q, y)) or (inside(q, x) and inside(p, y)):
                size = len(p) + len(q)
                if best is None or size > best[0]:
                    best = (size, metres)
        return best[1] if best else None

    def fastest(self) -> float | None:
        """The most metres a day any `speed` row allows, or None without one."""
        return max(self.speeds.values()) if self.speeds else None


def path_for(project_dir: str) -> str:
    return os.path.join(project_dir, 'reference', WORLD_FILE)


def _rows(path: str) -> tuple[list[str], list[tuple[int, list[str]]]]:
    with open(path, encoding='utf-8-sig', newline='') as f:
        lines = f.read().splitlines()
    if not lines:
        return [], []
    header = [c.strip() for c in lines[0].split('|')]
    rows = [(n, [c.strip() for c in line.split('|')])
            for n, line in enumerate(lines[1:], start=2) if line.strip()]
    return header, rows


def problems(path: str) -> list[str]:
    """What's wrong with the table at `path`, one line each naming the row
    ([] when it's sound or absent). Reading fails are problems too."""
    if not os.path.isfile(path):
        return []
    try:
        header, rows = _rows(path)
    except (OSError, UnicodeDecodeError) as e:
        return [f'could not be read ({type(e).__name__})']
    if header != list(COLUMNS):
        return [f'header is "{"|".join(header)}", not "{"|".join(COLUMNS)}"']
    out = []
    seen: dict[tuple[str, object], int] = {}
    for n, cells in rows:
        if len(cells) != len(COLUMNS):
            out.append(f'row {n} has {len(cells)} cells, not {len(COLUMNS)}')
            continue
        kind, name, value, _ = cells
        if kind not in KINDS:
            out.append(f'row {n}: kind "{kind}" is not one of {", ".join(KINDS)}')
            continue
        if not _key(name):
            out.append(f'row {n}: no name')
            continue
        key: object = _key(name)
        if kind == 'direction' and not compass(value):
            out.append(f'row {n}: direction "{value}" is not a compass direction')
        elif kind == 'sun' and not (compass(value) or value.lower() == SUN_DOWN):
            out.append(f'row {n}: sun "{value}" is not a compass direction or "{SUN_DOWN}"')
        elif kind in ('sight', 'distance') and _number(value) is None:
            out.append(f'row {n}: {kind} "{value}" is not a positive number of metres')
        elif kind == 'speed' and _number(value) is None:
            out.append(f'row {n}: speed "{value}" is not a positive number of metres a day')
        if kind == 'distance':
            pair = _pair(name)
            if pair is None:
                out.append(f'row {n}: distance name "{name}" is not two places as "A > B"')
                continue
            key = frozenset(pair)
        if (kind, key) in seen:
            out.append(f'row {n}: {kind} "{name}" is already given on row {seen[(kind, key)]}')
        else:
            seen[(kind, key)] = n
    return out


def load(project_dir: str) -> World:
    """The project's world table over the defaults. Raises `WorldTableError`
    when the file is there and has any `problems`."""
    path = path_for(project_dir)
    world = World()
    if not os.path.isfile(path):
        return world
    found = problems(path)
    if found:
        raise WorldTableError(f'reference/{WORLD_FILE}: {found[0]}'
                              + (f' (and {len(found) - 1} more)' if len(found) > 1 else '')
                              + '; `storyforge cleanup` lists them')
    _, rows = _rows(path)
    for _, (kind, name, value, _note) in rows:
        if kind == 'direction':
            world.directions[_key(name)] = compass(value)
        elif kind == 'sun':
            world.sun_at[_key(name)] = compass(value) or SUN_DOWN
        elif kind == 'sight':
            world.sight_m[_key(name)] = _number(value)
        elif kind == 'distance':
            world.distances[frozenset(_pair(name))] = _number(value)
        elif kind == 'speed':
            world.speeds[_key(name)] = _number(value)
    return world
