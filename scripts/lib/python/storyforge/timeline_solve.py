"""The calendar computed from the cues: the model labels time, code counts (#351).

The assignment pass asked a model for an integer day per scene. Models read
time well and count it badly: The Plastic Age's prom landed in January
(F-071), its exams in the junior year (F-072), and the days drifted between
runs at temperature 0 (F-073: 3 to 14 of 17 gold anchors held across six
runs). Here the cues the model has already read (``timeline.CUE_FIELDS``:
relation, gap, anchor, span, date) are the only input, and every day is
computed:

1. **Links.** Each scene on the story's present is joined to the present
   scene before it by its relation and gap: ``continues`` on the same day, a
   counted gap ("three weeks") as that many days, give or take a little, a
   vague one ("some weeks later") as a range with a preferred size. After a
   summary the gap counts from the end of its stretch when the stretch is
   counted.
2. **Anchors.** A stated month and day (the cue's EDTF ``date``), or a month
   or season the cue's ``anchor`` names (``timeline.anchor_window``), is a
   window in the year. A stated year with its month and day fixes the
   distance to every other such date.
3. **Solve.** For each day of the year day 1 could fall on, the present is
   walked in order: each anchored scene is placed at the day in its window
   that the links before it can reach, nearest their preferred sum; the
   difference is spread over the vague links before it, never the counted
   ones beyond their slack. The start of the year that keeps the most
   anchors, then moves the vague gaps least, wins. An anchor no reachable
   day keeps is a **conflict**, reported, not forced.
4. **Off the present.** A flashback (``earlier``) is placed back from the
   present by its counted gap, or by its vague gap's preferred size; a scene
   that continues a flashback stays in it, and a ``later`` one comes back to
   the present. A frame is placed after the
   story's last day, a vision on its viewer's day.

Deterministic, no model calls. ``solve(items)`` takes ``timeline.scene_items``
rows; ``run_solve`` writes ``scenes.csv`` like ``timeline.run_assignment``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from .timeline import _month_day, _rough_date, anchor_window, gap_to_days

YEAR = 365

# Vague gaps: (fewest days, most, preferred). The first pattern that
# matches wins; anything else "later" is a short, free gap
_VAGUE = [
    (re.compile(r'\b(decades?|generations?|a lifetime)\b'), (3650, 36500, 7300)),
    (re.compile(r'\b(many|several|some|a few|few|long) years?\b|\byears\b'), (730, 7300, 1825)),
    (re.compile(r'\b(a|one|another) year\b|\byear later\b'), (300, 450, 365)),
    (re.compile(r'\b(many|several|some|a few|few) months\b|\bmonths\b'), (45, 300, 90)),
    (re.compile(r'\b(a month|month)\b'), (21, 45, 30)),
    (re.compile(r'\b(summer|winter|spring|autumn|fall|season|term|semester|vacation|'
                r'holidays?|year)\b'), (21, 150, 60)),
    (re.compile(r'\b(many|several|some|a few|few) weeks\b|\bweeks\b'), (10, 70, 21)),
    (re.compile(r'\b(a week|week|fortnight)\b'), (5, 16, 7)),
    (re.compile(r'\b(many|several|some|a few|few|couple of|a couple of) days\b|\bdays\b'),
     (2, 10, 3)),
    (re.compile(r'\b(next|following|after|tomorrow|overnight)\b'), (1, 2, 1)),
    (re.compile(r'\b(hours?|minutes?|moments?|soon|shortly|that (morning|evening|night)|'
                r'same|immediately|meanwhile)\b'), (0, 1, 0)),
]
# "later" with no gap: some days, free to stretch to an anchor
_LATER_FREE = (1, 120, 2)
# "unclear": anywhere from the same day to a season on
_UNCLEAR = (0, 120, 1)
# Slack on a counted gap: "three weeks" is 21 days, give or take
_COUNTED_SLACK = 0.15
# A month and day stated without "~" is held to this many days; with it,
# _APPROXIMATE days
_DATE_SLACK = 1
_APPROXIMATE = 7


@dataclass
class Link:
    lo: int
    hi: int
    pref: int
    counted: bool          # a stated, counted distance (its slack is small)


@dataclass
class Anchor:
    first: int             # day of the year, 0 = January 1
    last: int              # may be below first across the new year
    slack: int
    words: str
    year_date: date | None = None   # a stated year, month and day


@dataclass
class Solved:
    days: dict[str, int] = field(default_factory=dict)
    modes: dict[str, str] = field(default_factory=dict)
    basis: dict[str, str] = field(default_factory=dict)
    conflicts: list[tuple[str, str]] = field(default_factory=list)   # (scene id, message)
    day_one: int | None = None    # day of the year day 1 falls on, when anchors fix it


def link_for(relation: str, gap: str) -> Link:
    """How far a present scene is from the present scene before it."""
    text = (gap or '').strip().lower()
    if relation == 'continues' and not text:
        return Link(0, 0, 0, True)
    counted = gap_to_days(text)
    if counted is not None:
        if counted <= 2:
            return Link(counted, counted, counted, True)
        slack = max(1, round(counted * _COUNTED_SLACK))
        return Link(counted - slack, counted + slack, counted, True)
    for pattern, (lo, hi, pref) in _VAGUE:
        if pattern.search(text):
            return Link(lo, hi, pref, False)
    if relation == 'continues':
        return Link(0, 1, 0, False)
    if relation == 'unclear':
        return Link(*_UNCLEAR, False)
    return Link(*_LATER_FREE, False)


def anchor_for(cue: dict) -> Anchor | None:
    """The scene's place in the year, from its stated date or its anchor."""
    stated = (cue.get('date') or '').strip()
    md = _month_day(stated)
    if md:
        year, month, day = md
        doy = _doy(month, day)
        slack = _APPROXIMATE if re.search(r'[~?%]', stated) else _DATE_SLACK
        when = None
        if 'X' not in year:
            try:
                when = date(int(year), month, day)
            except ValueError:
                when = None
        return Anchor(doy, doy, slack, stated, when)
    rough = _rough_date(stated)
    # A stated month (not a season: the cue's season codes are too often
    # wrong, F-070) is a window
    if rough and rough[1] <= 15:
        middle, half, words = rough
        return Anchor((middle - half) % YEAR, (middle + half) % YEAR, 7, words)
    window = anchor_window(cue.get('anchor', ''))
    if window:
        first, last, words, slack = window
        return Anchor(first, last, slack, words)
    return None


def _doy(month: int, day: int) -> int:
    """Day of the year, 0 = January 1, on 2001's calendar."""
    try:
        return date(2001, month, day).timetuple().tm_yday - 1
    except ValueError:
        return date(2001, month, 28).timetuple().tm_yday - 1


def _off(doy: int, a: Anchor) -> int:
    """Days *doy* lies outside *a*'s window, 0 inside."""
    first, last = a.first, a.last
    inside = first <= doy <= last if first <= last else (doy >= first or doy <= last)
    if inside:
        return 0
    return min((first - doy) % YEAR, (doy - last) % YEAR)


def _span_days(span: str) -> int | None:
    """A summary's counted stretch ("the next four days"), else None."""
    days = gap_to_days(span or '')
    return days if days and days > 0 else None


def _place(base: int, links: list[Link], anchor: Anchor | None, day_one: int,
           year_ref: tuple[int, date] | None) -> tuple[int, bool]:
    """The day for the scene after *links*, counted from *base*, and whether
    its anchor holds. *day_one*: day 1's day of the year."""
    lo = base + sum(l.lo for l in links)
    hi = base + sum(l.hi for l in links)
    pref = base + sum(l.pref for l in links)
    if anchor is None:
        return pref, True
    if anchor.year_date is not None and year_ref is not None:
        exact = year_ref[0] + (anchor.year_date - year_ref[1]).days
        if lo - anchor.slack <= exact <= hi + anchor.slack:
            return exact, True
        return pref, False
    for slack in (0, anchor.slack):
        day = _nearest_in_window(lo, hi, pref, day_one, anchor, slack)
        if day is not None:
            return day, True
    # Vague gaps give way to an anchor: past their range, up to a year on
    if any(not l.counted for l in links):
        day = _nearest_in_window(lo, hi + YEAR, hi, day_one, anchor, anchor.slack)
        if day is not None:
            return day, True
    return pref, False


def _nearest_in_window(lo: int, hi: int, pref: int, day_one: int, anchor: Anchor,
                       slack: int) -> int | None:
    """The day in [lo, hi] nearest *pref* whose day of the year (day 1 on
    *day_one*) is in *anchor*'s window widened by *slack*, or None."""
    first = anchor.first - slack
    length = (anchor.last - anchor.first) % YEAR + 1 + 2 * slack
    if length >= YEAR:
        return max(lo, min(hi, pref))
    # Day d is in the window when (day_one + d - 1 - first) % YEAR < length
    start = first - day_one + 1          # a day whose doy is the window's first
    best = None
    k0 = (lo - start) // YEAR - 1
    k1 = (hi - start) // YEAR + 1
    for k in range(k0, k1 + 1):
        a = max(lo, start + k * YEAR)
        b = min(hi, start + k * YEAR + length - 1)
        if a > b:
            continue
        d = max(a, min(b, pref))
        if best is None or abs(d - pref) < abs(best - pref):
            best = d
    return best


def _spread(start: int, end: int, links: list[Link]) -> list[int]:
    """Days for the scenes joined by *links* from a scene on *start* to one
    on *end*: each link at its preferred size, the difference taken up by
    the vague links first (in proportion to their room), then the counted."""
    sizes = [l.pref for l in links]
    diff = end - start - sum(sizes)
    for counted in (False, True):
        if not diff:
            break
        room = [(l.hi - s if diff > 0 else s - l.lo) if l.counted == counted else 0
                for l, s in zip(links, sizes)]
        total = sum(room)
        if not total:
            continue
        take = max(-total, min(total, diff)) if diff < 0 else min(total, diff)
        moved = 0
        for i, r in enumerate(room):
            if not r:
                continue
            share = round(abs(take) * r / total)
            share = min(share, r, abs(take) - moved)
            sizes[i] += share if diff > 0 else -share
            moved += share
        # rounding: give what's left to the roomiest link
        rest = abs(take) - moved
        while rest > 0:
            i = max(range(len(room)), key=lambda k: (room[k] - abs(sizes[k] - links[k].pref)))
            if room[i] - abs(sizes[i] - links[i].pref) <= 0:
                break
            sizes[i] += 1 if diff > 0 else -1
            rest -= 1
        diff = end - start - sum(sizes)
    if diff:
        # Past every range: the vaguest link takes the rest
        vague = [i for i, l in enumerate(links) if not l.counted] or list(range(len(links)))
        i = max(vague, key=lambda k: links[k].hi - links[k].lo)
        sizes[i] += diff
        if sizes[i] < 0 and diff < 0:
            sizes[i] = 0
    days, day = [], start
    for s in sizes:
        day += s
        days.append(day)
    return days


def _walk_present(present: list[tuple[str, Link, Anchor | None]], day_one: int):
    """Place the present scenes for one start of the year. Returns (days,
    kept, missed ids, stretch)."""
    days: dict[str, int] = {}
    if not present:
        return days, 0, [], 0
    first_id = present[0][0]
    days[first_id] = 1
    kept, missed, stretch = 0, [], 0
    year_ref = None
    if present[0][2] is not None:
        a = present[0][2]
        if _off((day_one) % YEAR, a) <= a.slack:
            kept += 1
            if a.year_date is not None:
                year_ref = (1, a.year_date)
        else:
            missed.append(first_id)
    base_id, base_day = first_id, 1
    pending: list[tuple[str, Link]] = []
    for sid, link, anchor in present[1:]:
        pending.append((sid, link))
        if anchor is None:
            continue
        links = [l for _s, l in pending]
        day, held = _place(base_day, links, anchor, day_one, year_ref)
        if held:
            kept += 1
            if anchor.year_date is not None and year_ref is None:
                year_ref = (day, anchor.year_date)
        else:
            missed.append(sid)
        placed = _spread(base_day, day, links)
        stretch += abs(day - (base_day + sum(l.pref for l in links)))
        for (s, _l), d in zip(pending, placed):
            days[s] = d
        base_id, base_day, pending = sid, day, []
    if pending:
        placed = _spread(base_day, base_day + sum(l.pref for _s, l in pending),
                         [l for _s, l in pending])
        for (s, _l), d in zip(pending, placed):
            days[s] = d
    return days, kept, missed, stretch


def solve(items: list[dict]) -> Solved:
    """Every scene's day, from its cues. *items*: ``timeline.scene_items``
    rows (id, duration, cues) in reading order."""
    out = Solved()
    # 1. Sort the scenes into the present chain and the scenes off it
    present: list[tuple[str, Link, Anchor | None]] = []
    role: dict[str, tuple] = {}     # sid -> ('present',) | ('earlier', ...) | ...
    last_present_span = None
    in_flashback = False
    started = False
    after_frame = False
    for it in items:
        sid = it['id']
        cue = it.get('cues') or {}
        relation = (cue.get('relation') or 'unclear').strip().lower()
        gap = cue.get('gap', '')
        if relation in ('frame', 'vision'):
            role[sid] = (relation,)
            after_frame = True
            continue
        # After frame narration, "earlier" is the story starting or coming
        # back, not a flashback (Gatsby opens with Nick looking back)
        if after_frame and relation == 'earlier':
            relation, gap = 'continues', ''
        after_frame = False
        if not started:
            started = True
            if relation != 'earlier':
                present.append((sid, Link(0, 0, 0, True), anchor_for(cue)))
                role[sid] = ('present',)
                last_present_span = _span_days(cue.get('span', '')) if _is_summary(it) else None
                continue
        if relation == 'earlier':
            in_flashback = True
            role[sid] = ('earlier', link_for('later', gap), gap)
            continue
        if in_flashback and relation == 'continues':
            role[sid] = ('inside',)
            continue
        # "later" after a memory comes back to the present: back from a
        # flashback, "the next morning" counts from the present (Gatsby VIII)
        in_flashback = False
        link = link_for(relation, gap)
        if last_present_span and not link.counted:
            link = Link(link.lo + last_present_span, link.hi + last_present_span,
                        link.pref + last_present_span, False)
        elif last_present_span and link.counted:
            link = Link(link.lo + last_present_span, link.hi + last_present_span,
                        link.pref + last_present_span, True)
        present.append((sid, link, anchor_for(cue)))
        role[sid] = ('present',)
        last_present_span = _span_days(cue.get('span', '')) if _is_summary(it) else None

    # 2. The start of the year that keeps the most anchors, then stretches least
    anchored = sum(1 for _s, _l, a in present if a is not None)
    best = None
    for day_one in (range(YEAR) if anchored else [0]):
        days, kept, missed, stretch = _walk_present(present, day_one)
        key = (-kept, stretch, day_one)
        if best is None or key < best[0]:
            best = (key, day_one, days, missed)
    _key, day_one, days, missed = best
    out.day_one = day_one if anchored else None
    for sid in missed:
        a = next(a for s, _l, a in present if s == sid)
        out.conflicts.append((sid, f'no day the gaps before it allow falls in {a.words}'))

    # 3. The present, then the scenes off it, in reading order
    present_day = None
    last_day = None
    for it in items:
        sid = it['id']
        kind = role.get(sid, ('present',))[0]
        if kind == 'present':
            day = days[sid]
            out.modes[sid] = 'summary' if _is_summary(it) else 'scene'
            out.basis[sid] = 'from cues'
            present_day = day if present_day is None else max(present_day, day)
        elif kind == 'earlier':
            _k, link, gap = role[sid]
            back = link.pref if gap.strip() else 1
            day = (present_day if present_day is not None else 1) - max(back, 1)
            out.modes[sid] = 'scene'
            out.basis[sid] = f'earlier: {gap.strip() or "unstated"}'
        elif kind == 'inside':
            day = last_day if last_day is not None else 0
            out.modes[sid] = 'scene'
            out.basis[sid] = 'continues the memory'
        elif kind == 'vision':
            day = last_day if last_day is not None else 1
            out.modes[sid] = 'vision'
            out.basis[sid] = "the viewer's day"
            out.days[sid] = day
            continue
        else:   # frame: placed after the story's end, below
            out.modes[sid] = 'frame'
            out.basis[sid] = 'after the story'
            continue
        out.days[sid] = day
        last_day = day
    end = max(out.days.values(), default=1)
    for sid, mode in out.modes.items():
        if mode == 'frame':
            out.days[sid] = end + 1
    return out


def _is_summary(item: dict) -> bool:
    span = ((item.get('cues') or {}).get('span') or '').strip()
    return bool(span) and _span_days(span) is not None and _span_days(span) > 1



SOLVED_FILE = 'working/timeline-solved.csv'


def run_solve(project_dir: str) -> dict:
    """``timeline --solve``: the calendar computed from the stored cues,
    beside the days scenes.csv holds, written to ``working/timeline-solved.csv``.
    Report-only: scenes.csv is never changed. Returns counts: scenes, solved,
    conflicts, differ (scenes more than a day from the current day, once the
    two calendars are aligned on their median offset)."""
    import csv
    import os
    from .common import log
    from .elaborate import _read_csv
    from .timeline import _int, read_cues, scene_items
    cues = read_cues(project_dir)
    items = scene_items(project_dir, cues)
    no_cues = [it['id'] for it in items if not it.get('cues')]
    result = solve(items)
    current = {r['id']: _int(r.get('timeline_day'))
               for r in _read_csv(os.path.join(project_dir, 'reference', 'scenes.csv'))}
    offsets = sorted(result.days[s] - current[s] for s in result.days
                     if current.get(s) is not None and result.modes.get(s) == 'scene')
    shift = offsets[len(offsets) // 2] if offsets else 0
    conflicts = dict(result.conflicts)
    path = os.path.join(project_dir, SOLVED_FILE)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    differ = 0
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f, delimiter='|', lineterminator='\n')
        w.writerow(['id', 'current_day', 'solved_day', 'mode', 'basis', 'conflict'])
        for it in items:
            sid = it['id']
            day = result.days.get(sid)
            cur = current.get(sid)
            if day is not None and cur is not None and abs(day - shift - cur) > 1:
                differ += 1
            w.writerow([sid, '' if cur is None else cur,
                        '' if day is None else day - shift, result.modes.get(sid, ''),
                        result.basis.get(sid, ''), conflicts.get(sid, '')])
    log(f'Solved calendar: {len(result.days)} of {len(items)} scene(s) placed from the '
        f'stored cues, written to {SOLVED_FILE}; scenes.csv is unchanged')
    if no_cues:
        log(f'  WARNING: {len(no_cues)} scene(s) have no stored cues and were placed as '
            f'"unclear": ' + ', '.join(no_cues[:10]))
    if shift:
        log(f'  Aligned to the current calendar (shifted {-shift:+d} days)')
    log(f'  {differ} scene(s) more than a day from their current day')
    if result.conflicts:
        log(f'  {len(result.conflicts)} anchor(s) no day the gaps allow can keep:')
        for sid, message in result.conflicts[:20]:
            log(f'    {sid}: {message}')
    return {'scenes': len(items), 'solved': len(result.days),
            'conflicts': len(result.conflicts), 'differ': differ}
