"""The timeline pass: one calendar for the whole book.

Time is decided in two steps (docs/plans/timeline-pass.md):

1. **Cues per scene.** What a scene says about time, read from its prose (or
   its summary when there is no prose): its relation to the previous scene in
   reading order, the gap in words, a calendar anchor, a span, and a date in
   EDTF holding only what the text states. Cues never contain a day.
2. **Assignment in reading order.** Code walks the scenes with a running
   present, placing every scene whose cues are clear; the model resolves the
   rest in fixed-size batches (``scene_id | day | mode | basis``), each
   applied before the next with the present carried across. No call's output
   grows with the book.

Checks are deterministic and report, never rewrite: the present going
backwards on a scene not told as a flashback, a stated gap the days don't
match, dates or weekdays that contradict the days.
"""

import csv
import os
import re

from .common import log
from .enrich import update_csv_field


RELATIONS = ('continues', 'later', 'earlier', 'frame', 'unclear')
TIME_MODES = ('scene', 'summary', 'frame')

CUE_COLUMNS = ['id', 'relation', 'gap', 'anchor', 'refers', 'span', 'date']
CUES_FILE = os.path.join('working', 'timeline-cues.csv')
PROPOSED_FILE = os.path.join('working', 'timeline-proposed.csv')

_BATCH_SIZE = 40
# Reasoning (capped in the prompt) plus one line per scene: bounded by the
# batch size, never by the book. On Gatsby a 6,000-token budget was cut off
# mid-answer once the model worked through its anchors.
_BATCH_MAX_TOKENS = 16000


# ============================================================================
# Cues: the prompt fields, parsing and storage
# ============================================================================

CUE_INSTRUCTIONS = """TIME_RELATION: [when this scene happens relative to the scene before it in reading order — one of: continues (picks up at the same time or moments later), later (some time after it), earlier (before it: a flashback or a recollection told as a scene), frame (narration from after the story, looking back), unclear]
TIME_GAP: [the gap from the previous scene in at most six words, no explanation: "an hour", "the next morning", "three weeks", "five years", "several weeks"; empty if none is stated or implied]
TIME_ANCHOR: [a calendar fact pinning when THIS scene's action happens — a date, weekday, month, season, holiday or named day ("the hottest day of the summer") — quoted briefly; not a habit ("every Friday") or a date the scene only mentions; empty if none]
TIME_REFERS: [any statement in this scene of how long ago or how long until another event in the story, quoted briefly: "that June night three months before", "five years since he'd seen her", "the funeral was on the third day"; separate several with semicolons; empty if none]
TIME_SPAN: [when the scene summarizes a stretch of time ("all that summer"), how long; empty for a scene that plays out in one sitting]
TIME_DATE: [only what this scene's own text states about the calendar date, in EDTF: "1922-07-04", "XXXX-07-04" when the year isn't given here, "1922" for a year, "1922-22" for summer 1922 (21 spring, 22 summer, 23 autumn, 24 winter), "1917~" for "around 1917", "1922-06/1922-09" for a stretch. Never fill in a part the text doesn't give; empty if the text gives no date]"""

_CUE_LABELS = {
    'TIME_RELATION': 'relation',
    'TIME_GAP': 'gap',
    'TIME_ANCHOR': 'anchor',
    'TIME_REFERS': 'refers',
    'TIME_SPAN': 'span',
    'TIME_DATE': 'date',
}

_EMPTY_ANSWERS = {'', 'none', 'n/a', 'unknown', 'empty', '-', '(none)', '(empty)'}


def parse_cues(response: str) -> dict[str, str]:
    """Parse ``TIME_*`` lines into a cue dict (keys of CUE_COLUMNS but id).

    The relation is reduced to one of RELATIONS (``unclear`` when it is
    none of them); an invalid date is dropped rather than stored.
    """
    cues = {key: '' for key in _CUE_LABELS.values()}
    for line in (response or '').split('\n'):
        match = re.match(r'^\s*(TIME_[A-Z]+):\s*(.*)$', line)
        if not match or match.group(1) not in _CUE_LABELS:
            continue
        value = match.group(2).strip().strip('"').strip()
        if value.lower().strip('[]().') in _EMPTY_ANSWERS:
            value = ''
        cues[_CUE_LABELS[match.group(1)]] = value
    relation = cues['relation'].lower()
    cues['relation'] = next((r for r in RELATIONS if relation.startswith(r)), 'unclear')
    if cues['date'] and not is_valid_edtf(cues['date']):
        cues['date'] = ''
    return cues


def read_cues(project_dir: str) -> dict[str, dict[str, str]]:
    path = os.path.join(project_dir, CUES_FILE)
    if not os.path.isfile(path):
        return {}
    with open(path, newline='', encoding='utf-8') as f:
        return {row['id']: row for row in csv.DictReader(f, delimiter='|') if row.get('id')}


def write_cues(project_dir: str, cues: dict[str, dict[str, str]]) -> None:
    """Merge *cues* (scene id → cue dict) into working/timeline-cues.csv."""
    merged = read_cues(project_dir)
    for sid, cue in cues.items():
        merged[sid] = {'id': sid, **{k: cue.get(k, '') for k in CUE_COLUMNS[1:]}}
    path = os.path.join(project_dir, CUES_FILE)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=CUE_COLUMNS, delimiter='|', lineterminator='\n')
        w.writeheader()
        w.writerows(merged.values())


def build_cue_prompt(scene_id: str, text: str, previous_tail: str = '',
                     is_summary: bool = False) -> str:
    """Prompt for one scene's time cues, from its prose or (for a project not
    yet drafted) its summary and function."""
    what = 'scene summary' if is_summary else 'scene'
    previous = (f'## End of the Previous Scene\n\n{previous_tail}\n\n' if previous_tail
                else '## Previous Scene\n\n(this is the first scene)\n\n')
    return f"""Read this {what} from a novel and say what it tells us about time. Don't work out a day number: only what the text says.

{previous}## {'Summary' if is_summary else 'Scene'}: {scene_id}

{text}

## Instructions

Output each field on its own labeled line.

{CUE_INSTRUCTIONS}"""


def tail_words(text: str, n: int = 300) -> str:
    words = (text or '').split()
    return ' '.join(words[-n:])


# ============================================================================
# Gaps in words → days
# ============================================================================

_NUMBER_WORDS = {
    'a': 1, 'an': 1, 'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5,
    'six': 6, 'seven': 7, 'eight': 8, 'nine': 9, 'ten': 10, 'eleven': 11,
    'twelve': 12, 'fifteen': 15, 'twenty': 20, 'thirty': 30, 'forty': 40,
    'fifty': 50, 'a couple of': 2, 'a couple': 2, 'couple of': 2,
}
_TENS = {'twenty': 20, 'thirty': 30, 'forty': 40, 'fifty': 50, 'sixty': 60,
         'seventy': 70, 'eighty': 80, 'ninety': 90}
_UNIT_DAYS = {
    'minute': 0, 'hour': 0, 'day': 1, 'night': 1, 'week': 7, 'fortnight': 14,
    'month': 30, 'season': 91, 'year': 365, 'decade': 3650,
}
_SAME_DAY = re.compile(
    r'\b(same (moment|time|day|evening|night|afternoon|morning)|moments? later|'
    r'immediately|minutes? later|an? (hour|few hours|couple of hours) later|'
    r'that (morning|afternoon|evening|night)|later that|meanwhile|'
    r'(this|the) (afternoon|evening)|continu)', re.IGNORECASE)
_NEXT_DAY = re.compile(
    r'\b(next (day|morning|afternoon|evening|night)|following (day|morning|evening|night)|'
    r'tomorrow|the day after|overnight)\b', re.IGNORECASE)


def gap_to_days(gap: str) -> int | None:
    """Days spanned by a gap phrase, or None when it is vague ("some time
    later", "a few weeks") or absent. Years count as 365 days, months as 30:
    order and rough depth are what matter."""
    text = (gap or '').strip().lower()
    # An explanation, not a gap: a phrase picked out of it would be a guess
    if not text or len(text.split()) > 8:
        return None
    if _SAME_DAY.search(text) and not re.search(r'\b(days?|weeks?|months?|years?)\b', text):
        return 0
    if _NEXT_DAY.search(text):
        return 1
    tens = re.search(r'\b(twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)-'
                     r'(one|two|three|four|five|six|seven|eight|nine)\s+'
                     r'(day|week|month|year)s?\b', text)
    if tens:
        n = _TENS[tens.group(1)] + _NUMBER_WORDS[tens.group(2)]
        return n * _UNIT_DAYS[tens.group(3)]
    match = re.search(
        r'\b(\d+|a couple of|a couple|couple of|' + '|'.join(
            sorted((w for w in _NUMBER_WORDS if ' ' not in w), key=len, reverse=True))
        + r')\s+(minute|hour|day|night|week|fortnight|month|season|year|decade)s?\b', text)
    if not match:
        return None
    count = match.group(1)
    n = int(count) if count.isdigit() else _NUMBER_WORDS[count]
    return n * _UNIT_DAYS[match.group(2)]


# ============================================================================
# EDTF dates (the subset timeline_date accepts)
# ============================================================================

_EDTF_DATE = re.compile(
    r'^(?P<year>[0-9X]{4})'
    r'(?:-(?P<month>[0-9X]{2})(?:-(?P<day>[0-9X]{2}))?)?'
    r'(?P<qual>[?~%])?$')


def _edtf_date_ok(value: str) -> bool:
    m = _EDTF_DATE.match(value)
    if not m or not re.search(r'\d', value):
        return False
    month, day = m.group('month'), m.group('day')
    if month and 'X' not in month:
        mi = int(month)
        if not (1 <= mi <= 12 or (21 <= mi <= 24 and not day)):
            return False
    if day and 'X' not in day and not 1 <= int(day) <= 31:
        return False
    return True


def is_valid_edtf(value: str) -> bool:
    """Whether *value* is in the EDTF subset ``timeline_date`` accepts: a
    year, year-month or year-month-day with ``X`` for any unknown digit
    (``XXXX-07-04``), a season (``1922-22``), an optional trailing ``?``,
    ``~`` or ``%``, or an interval of two of those (``1922-06/1922-09``,
    ``../1922``). At least one digit must be known."""
    value = (value or '').strip()
    if not value:
        return False
    if '/' in value:
        start, _, end = value.partition('/')
        ends = [e for e in (start, end) if e not in ('', '..')]
        return bool(ends) and all(_edtf_date_ok(e) for e in ends)
    return _edtf_date_ok(value)


_MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August',
           'September', 'October', 'November', 'December']
_SEASONS = {21: 'spring', 22: 'summer', 23: 'autumn', 24: 'winter'}


def describe_edtf(value: str) -> str:
    """An EDTF date in words, for prompts: models read ``1922-22`` (summer
    1922) as June 22. ``XXXX-07-04`` → "4 July (year not stated)"."""
    value = (value or '').strip()
    if '/' in value:
        start, _, end = value.partition('/')
        parts = [describe_edtf(p) if p not in ('', '..') else 'open' for p in (start, end)]
        return f'from {parts[0]} to {parts[1]}'
    m = _EDTF_DATE.match(value)
    if not m:
        return value
    year, month, day, qual = m.group('year'), m.group('month'), m.group('day'), m.group('qual')
    words = []
    if day and 'X' not in day:
        words.append(str(int(day)))
    if month and 'X' not in month:
        mi = int(month)
        words.append(_SEASONS.get(mi) or _MONTHS[mi - 1])
    year_text = year if 'X' not in year else ('' if year == 'XXXX' else year.replace('X', '?'))
    text = ' '.join(words + ([year_text] if year_text else []))
    if year == 'XXXX':
        text += ' (year not stated)'
    if qual:
        text += {'~': ', approximately', '?': ', uncertain', '%': ', approximate and uncertain'}[qual]
    return text


def _month_day(value: str) -> tuple[str, int, int] | None:
    """``(year, month, day)`` for a single EDTF date with a known month and
    day (year may be ``XXXX``), else None."""
    m = _EDTF_DATE.match((value or '').strip())
    if not m or not m.group('day'):
        return None
    month, day = m.group('month'), m.group('day')
    if 'X' in month or 'X' in day or int(month) > 12:
        return None
    return m.group('year'), int(month), int(day)


# ============================================================================
# Assignment: the running-present walk, then batches
# ============================================================================

def walk(order: list[str], cues: dict[str, dict], last: int | None = None,
         present: int | None = None) -> dict[str, int | None]:
    """Provisional days from the cues alone, in reading order.

    A scene is placed relative to the previous scene: ``continues`` on its
    day, ``later``/``earlier`` by a parseable gap. After a flashback scene a
    ``continues`` stays in the flashback (Gatsby VIII runs 1917 into 1919),
    but a ``later`` is left for the model: code can't tell "later in the
    memory" from "back to the present", and counting from the remembered day
    would put the present years in the past. The first scene that isn't frame
    narration is day 1 unless it is a flashback. A scene after a frame
    interjection is read against the scene before the frame, and an
    ``earlier`` there is a return from the frame, not a flashback. Frame
    scenes, unclear ones, vague gaps and anything after an unplaced scene
    stay None for the model. *last* and *present* continue a walk begun in
    an earlier batch.
    """
    days: dict[str, int | None] = {}
    started = last is not None
    after_frame = False
    for sid in order:
        cue = cues.get(sid, {})
        relation = cue.get('relation') or 'unclear'
        gap = gap_to_days(cue.get('gap', ''))
        if relation == 'frame':
            days[sid] = None
            after_frame = True
            continue
        if after_frame and relation == 'earlier':
            relation, gap = 'continues', None
        after_frame = False
        in_flashback = last is not None and present is not None and last < present
        day = None
        # The clock starts at the first scene that isn't frame narration
        # (Gatsby opens with Nick looking back)
        if not started:
            started = True
            if relation in ('continues', 'later', 'unclear'):
                day = 1
        elif last is not None and relation == 'continues':
            day = last
        elif last is not None and relation == 'later' and gap is not None and not in_flashback:
            day = last + gap
        elif last is not None and relation == 'earlier' and gap is not None:
            day = last - gap
        days[sid] = day
        last = day
        if day is not None and relation != 'earlier' and (present is None or day > present):
            present = day
    return days


def build_assignment_prompt(batch: list[dict], present: int | None,
                            last_day: int | None, anchors: list[str],
                            terse: bool = False) -> str:
    """Prompt placing one batch of scenes on the calendar.

    Each item: id, title, summary, time_of_day, duration, cues, provisional.
    """
    lines = []
    for item in batch:
        cue = item.get('cues', {})
        parts = [f'relation {cue.get("relation") or "unclear"}']
        for key in ('gap', 'anchor', 'refers', 'span'):
            if cue.get(key):
                parts.append(f'{key} "{cue[key]}"')
        if cue.get('date'):
            parts.append(f'date stated: {describe_edtf(cue["date"])}')
        provisional = item.get('provisional')
        lines.append(
            f'{item["id"]} — {item.get("title", "")}\n'
            f'  {item.get("summary", "")}\n'
            f'  time of day: {item.get("time_of_day") or "?"}; duration: {item.get("duration") or "?"}\n'
            f'  cues: {"; ".join(parts)}\n'
            f'  provisional day: {provisional if provisional is not None else "?"}')
    anchor_text = '\n'.join(f'- {a}' for a in anchors[-30:]) or '(none yet)'
    return f"""You are placing the scenes of a novel on one calendar. Day 1 is the first day of the main story; a scene set before it gets day 0 or a negative day (five years before is about -1825). Scenes are listed in reading order.

## Where the Calendar Stands

The story's present (latest day the main story has reached): {present if present is not None else "not started (this is the first batch)"}
The previous scene's day: {last_day if last_day is not None else "none"}

Anchors placed so far:
{anchor_text}

## Scenes

{chr(10).join(lines)}

## Instructions

Each scene's cues say how it relates to the scene before it. A provisional day was computed from clear cues; keep it unless an anchor, the summary or the surrounding scenes show it is wrong, and decide every "?".

- earlier: a flashback or recollection; it gets the earlier day it depicts and does not move the present.
- frame: narration from after the story; it gets the day it is narrated from (after the story's end, roughly) and does not move the present.
- A date anchor pins a scene: keep dates consistent with the days between them. Weekdays are weak evidence (characters misname days, and "Saturday" may be a day mentioned rather than the scene's own): use them where they agree, and where they conflict, drop them rather than work them out.
- "refers" cues state how far apart two events are ("that June night three months before" puts this scene about 90 days after that night). They are the firmest evidence of distance: where vague gaps ("several weeks", "some time later") add up to something else, stretch or shrink the vague gaps to fit the stated durations, counting back as well as forward.
- mode: scene (the action plays out on its day), summary (it covers a stretch of time; the day is where the stretch starts), or frame.

{"Write a line CALENDAR: and nothing before it; after it" if terse else "First work out the calendar under a line REASONING: — list the anchors and every stated duration (refers), fix the days they pin, then fit the vague gaps between them; note any scene you are unsure of — in at most 600 words. Then write a line CALENDAR: and, after it,"} exactly one line per scene, in order:

scene_id | day | mode | basis

basis: a few words on why ("next morning", "anchor: July 4", "1917, five years before"). Nothing after the calendar lines."""


def parse_assignments(response: str, ids: list[str]) -> dict[str, tuple[int, str, str]]:
    """Parse ``scene_id | day | mode | basis`` lines for the scenes in *ids*.

    Days may be zero or negative. A missing or unknown mode comes back as
    ``''`` for the caller to decide. Lines for other ids or with a
    non-integer day are ignored.
    """
    wanted = set(ids)
    result: dict[str, tuple[int, str, str]] = {}
    # Only the answer after CALENDAR: counts; reasoning above it may try out
    # days it then revises
    text = response or ''
    marker = re.search(r'^\s*CALENDAR:\s*$', text, re.MULTILINE)
    if marker:
        text = text[marker.end():]
    for line in text.split('\n'):
        parts = [p.strip() for p in line.strip().lstrip('-* ').split('|')]
        if len(parts) < 2 or parts[0] not in wanted:
            continue
        try:
            day = int(parts[1].lstrip('+'))
        except ValueError:
            continue
        mode = parts[2].lower() if len(parts) > 2 and parts[2].lower() in TIME_MODES else ''
        basis = parts[3] if len(parts) > 3 else ''
        result[parts[0]] = (day, mode, basis)
    return result


def assign_calendar(items: list[dict], invoke, log_dir: str) -> dict[str, tuple[int, str, str]]:
    """Place every scene in *items* (reading order) on the calendar.

    *items*: dicts with id, title, summary, time_of_day, duration, cues.
    *invoke(prompt, log_file, label)* returns the response text, or None when
    the call failed or was cut off. Each batch's provisional days are walked
    from where the previous batch left the calendar, so an anchor that moved
    batch 1 carries into batch 2. Returns scene id → (day, mode, basis); a
    scene in a failed batch keeps its provisional day if it has one, else is
    absent.
    """
    placed: dict[str, tuple[int, str, str]] = {}
    present: int | None = None
    last_day: int | None = None
    anchors: list[str] = []
    batches = [items[i:i + _BATCH_SIZE] for i in range(0, len(items), _BATCH_SIZE)]
    for n, batch in enumerate(batches, 1):
        provisional = walk([it['id'] for it in batch],
                           {it['id']: it.get('cues', {}) for it in batch},
                           last=last_day, present=present)
        for it in batch:
            it['provisional'] = provisional[it['id']]
        label = f'timeline (batch {n} of {len(batches)})'
        text = invoke(build_assignment_prompt(batch, present, last_day, anchors),
                      os.path.join(log_dir, f'timeline-assign-{n}.json'), label)
        if text is None:
            # A model can reason past any budget (shared-dark: 7,000 words on
            # weekday arithmetic, no answer). Ask once more for the answer only.
            log(f'  {label}: asking again for the calendar lines only')
            text = invoke(build_assignment_prompt(batch, present, last_day, anchors, terse=True),
                          os.path.join(log_dir, f'timeline-assign-{n}-retry.json'),
                          f'{label}, answer only')
        answers = parse_assignments(text, [it['id'] for it in batch]) if text is not None else {}
        for it in batch:
            sid = it['id']
            cue = it.get('cues', {})
            if sid in answers:
                day, mode, basis = answers[sid]
                # A line that lost its mode column ("id | 800 | frame
                # narration") must not make a frame the story's present
                if not mode:
                    mode = 'frame' if cue.get('relation') == 'frame' else 'scene'
                placed[sid] = (day, mode, basis)
            elif it['provisional'] is not None:
                placed[sid] = (it['provisional'], 'scene', 'from cues')
            if sid not in placed:
                continue
            day, mode, _basis = placed[sid]
            if mode != 'frame':
                last_day = day
                if cue.get('relation') != 'earlier' and (present is None or day > present):
                    present = day
            for key in ('anchor', 'refers', 'date'):
                if cue.get(key):
                    text = describe_edtf(cue[key]) if key == 'date' else cue[key]
                    anchors.append(f'{sid}: day {day} — {text}')
    return placed


# ============================================================================
# Checks (deterministic; reported, never applied)
# ============================================================================

_WEEKDAYS = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']


def _int(value) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def check_timeline(scenes: list[dict], cues: dict[str, dict]) -> list[dict]:
    """Inconsistencies between days, modes, cues and dates.

    *scenes*: scenes.csv rows in reading order. Returns findings
    ``{'scene_id', 'check', 'message'}``. Checks: the present going
    backwards on a scene not told as earlier and not a frame; a stated gap
    the days disagree with; two dates, or two weekdays, the days contradict.
    """
    findings = []
    present = None
    last_day = None
    last_mode = ''
    after_frame = False
    dated: list[tuple[str, int, tuple]] = []
    weekdays: list[tuple[str, int, int]] = []
    for row in scenes:
        sid = row.get('id', '')
        day = _int(row.get('timeline_day'))
        mode = (row.get('time_mode') or 'scene').strip() or 'scene'
        cue = cues.get(sid, {})
        relation = cue.get('relation', '')
        if mode == 'frame':
            after_frame = True
            continue
        if day is None:
            continue
        # A scene after a frame interjection relates to the frame, not to
        # the scene before it, so its relation and gap say nothing here
        if after_frame:
            relation, cue = '', {}
        after_frame = False
        # Only a step back from the present counts: a scene that continues
        # inside a flashback is behind the present too, legitimately
        at_present = last_day is not None and present is not None and last_day >= present
        if at_present and day < present and relation and relation != 'earlier':
            findings.append({'scene_id': sid, 'check': 'present_backwards',
                             'message': f'day {day} is before the story\'s present (day {present}) '
                                        f'but the scene reads as "{relation}", not a flashback'})
        if relation == 'earlier' and last_day is not None and day >= last_day:
            findings.append({'scene_id': sid, 'check': 'flashback_not_earlier',
                             'message': f'reads as set earlier, but its day ({day}) is not before '
                                        f'the previous scene\'s ({last_day})'})
        gap = gap_to_days(cue.get('gap', ''))
        # After a summary the gap counts from the end of a stretch whose
        # length is only roughly known, so it isn't checked
        if (last_day is not None and gap is not None and last_mode != 'summary'
                and relation in ('continues', 'later')):
            # Back from a flashback, "the next morning" counts from the
            # present, not from the remembered scene before it
            base = present if (present is not None and last_day < present <= day) else last_day
            actual = day - base
            if abs(actual - gap) > max(1, gap // 2):
                findings.append({'scene_id': sid, 'check': 'gap_mismatch',
                                 'message': f'the text says "{cue["gap"]}" (about {gap} day(s)), '
                                            f'but the calendar puts it {actual} day(s) on'})
        md = _month_day(row.get('timeline_date', ''))
        if md:
            dated.append((sid, day, md))
        anchor = (cue.get('anchor') or '').lower()
        named = [i for i, w in enumerate(_WEEKDAYS) if re.search(rf'\b{w}s?\b', anchor)]
        # One weekday, on a scene that happens on one day: a summary's
        # "Sunday mornings" is a habit, not a date
        weekday = named[0] if len(named) == 1 and mode == 'scene' else None
        if weekday is not None:
            weekdays.append((sid, day, weekday))
        last_day = day
        last_mode = mode
        if relation != 'earlier' and (present is None or day > present):
            present = day

    from datetime import date
    for (s1, d1, (y1, m1, dd1)), (s2, d2, (y2, m2, dd2)) in zip(dated, dated[1:]):
        # Compare within one stated year, or within an unstated one when the
        # days are less than a year apart
        if y1 != y2 or ('X' in y1 and abs(d2 - d1) >= 365):
            continue
        year = 2001 if 'X' in y1 else int(y1)
        try:
            between = (date(year, m2, dd2) - date(year, m1, dd1)).days
            # With the year unstated, December 30 then January 2 may
            # simply cross into the next year
            if 'X' in y1 and between < 0:
                between = (date(year + 1, m2, dd2) - date(year, m1, dd1)).days
        except ValueError:
            continue
        if abs(between - (d2 - d1)) > 1:
            findings.append({'scene_id': s2, 'check': 'date_mismatch',
                             'message': f'its date is {between} day(s) after {s1}\'s, '
                                        f'but its day is {d2 - d1} day(s) after'})
    for (s1, d1, w1), (s2, d2, w2) in zip(weekdays, weekdays[1:]):
        if (d2 - d1 - (w2 - w1)) % 7:
            findings.append({'scene_id': s2, 'check': 'weekday_mismatch',
                             'message': f'a {_WEEKDAYS[w2].title()} {d2 - d1} day(s) after '
                                        f'{s1}\'s {_WEEKDAYS[w1].title()}'})
    return findings


# ============================================================================
# Running the pass on a project
# ============================================================================

def scene_items(project_dir: str, cues: dict[str, dict]) -> list[dict]:
    """The book's scenes in reading order (cut and merged ones left out),
    with what the assignment prompt shows of each."""
    from .elaborate import _read_csv, _read_csv_as_map
    ref_dir = os.path.join(project_dir, 'reference')
    intent = _read_csv_as_map(os.path.join(ref_dir, 'scene-intent.csv'))
    rows = [r for r in _read_csv(os.path.join(ref_dir, 'scenes.csv'))
            if (r.get('status') or '').strip() not in ('cut', 'merged')]
    rows.sort(key=lambda r: _int(r.get('seq')) or 0)
    return [{
        'id': r['id'], 'title': r.get('title', ''),
        'summary': (r.get('summary') or intent.get(r['id'], {}).get('function') or '')[:300],
        'time_of_day': r.get('time_of_day', ''), 'duration': r.get('duration', ''),
        'cues': cues.get(r['id'], {}),
    } for r in rows]


def _invoke_assignment(model: str):
    from .api import invoke_to_file, extract_text_from_file, is_truncated

    def invoke(prompt, log_file, label):
        try:
            # Temperature 0: the same cues should give the same calendar
            response = invoke_to_file(prompt, model, log_file, max_tokens=_BATCH_MAX_TOKENS,
                                      label=label, temperature=0)
        except Exception as e:  # noqa: BLE001 — one failed batch, not the pass
            log(f'  WARNING: {label} failed ({e}); its scenes keep their provisional days')
            return None
        if is_truncated(response):
            log(f'  WARNING: {label} hit the {_BATCH_MAX_TOKENS}-token limit; '
                f'its scenes keep their provisional days')
            return None
        return extract_text_from_file(log_file)
    return invoke


def run_assignment(project_dir: str, model: str, log_dir: str, force: bool) -> dict:
    """Assign every scene a day and a time_mode from the stored cues, then
    run the checks.

    Empty fields are filled. A day or mode already set is replaced only with
    *force* (extraction, where nobody authored them); otherwise the full
    proposal goes to working/timeline-proposed.csv and the differences are
    reported. Returns counts: assigned, proposed, unplaced, findings.
    """
    from .elaborate import _read_csv, _write_csv, _FILE_MAP
    os.makedirs(log_dir, exist_ok=True)
    cues = read_cues(project_dir)
    items = scene_items(project_dir, cues)
    if not items:
        return {'assigned': 0, 'proposed': 0, 'unplaced': 0, 'findings': 0}
    placed = assign_calendar(items, _invoke_assignment(model), log_dir)

    scenes_path = os.path.join(project_dir, 'reference', 'scenes.csv')
    rows = _read_csv(scenes_path)
    # A calendar is one piece: where the author has set any day, a new one
    # is only proposed, never mixed in (its days may be offset from theirs)
    authored = any((r.get('timeline_day') or '').strip() for r in rows if r.get('id') in placed)
    write = force or not authored
    assigned = 0
    differences = []
    for row in rows:
        sid = row.get('id', '')
        if sid not in placed:
            continue
        day, mode, basis = placed[sid]
        for col, new in (('timeline_day', str(day)), ('time_mode', mode)):
            old = (row.get(col) or '').strip()
            if old == new or (col == 'time_mode' and not old and new == 'scene' and not write):
                continue
            if write:
                row[col] = new
                assigned += 1
            else:
                differences.append((sid, col, old, new, basis))
    if assigned:
        _write_csv(scenes_path, rows, _FILE_MAP['scenes.csv'])

    proposed_path = os.path.join(project_dir, PROPOSED_FILE)
    if differences:
        with open(proposed_path, 'w', newline='', encoding='utf-8') as f:
            w = csv.writer(f, delimiter='|', lineterminator='\n')
            w.writerow(['id', 'field', 'current', 'proposed', 'basis'])
            w.writerows(differences)
        log(f'  Timeline: days are set already, so nothing was changed; {len(differences)} '
            f'difference(s) proposed in {PROPOSED_FILE} (--force replaces)')
    elif os.path.isfile(proposed_path):
        os.remove(proposed_path)

    unplaced = [it['id'] for it in items if it['id'] not in placed]
    if unplaced:
        log(f'  WARNING: {len(unplaced)} scene(s) could not be placed: '
            + '; '.join(unplaced[:10]))
    findings = check_timeline(
        sorted((r for r in rows if (r.get('status') or '') not in ('cut', 'merged')),
               key=lambda r: _int(r.get('seq')) or 0), cues)
    report_findings(findings)
    return {'assigned': assigned, 'proposed': len(differences),
            'unplaced': len(unplaced), 'findings': len(findings)}


def scene_text(project_dir: str, scene_id: str) -> tuple[str, bool]:
    """A scene's prose, or (for a project not yet drafted) its summary and
    function. Returns (text, is_summary)."""
    path = os.path.join(project_dir, 'scenes', f'{scene_id}.md')
    if os.path.isfile(path):
        with open(path, encoding='utf-8') as f:
            prose = f.read()
        if prose.strip():
            return prose, False
    from .elaborate import _read_csv_as_map
    ref_dir = os.path.join(project_dir, 'reference')
    scene = _read_csv_as_map(os.path.join(ref_dir, 'scenes.csv')).get(scene_id, {})
    intent = _read_csv_as_map(os.path.join(ref_dir, 'scene-intent.csv')).get(scene_id, {})
    parts = [scene.get('summary', ''), intent.get('function', '')]
    return '\n\n'.join(p for p in parts if p and p.strip()), True


def reading_order(project_dir: str) -> list[str]:
    return [it['id'] for it in scene_items(project_dir, {})]


def cue_prompts(project_dir: str, scene_ids: list[str]) -> dict[str, str]:
    """Cue prompts for *scene_ids*, each with the end of the scene before it
    in the book's reading order."""
    order = reading_order(project_dir)
    prompts = {}
    for sid in scene_ids:
        text, is_summary = scene_text(project_dir, sid)
        if not text.strip():
            continue
        i = order.index(sid) if sid in order else -1
        previous = scene_text(project_dir, order[i - 1])[0] if i > 0 else ''
        prompts[sid] = build_cue_prompt(sid, text, tail_words(previous), is_summary)
    return prompts


def extract_cues(project_dir: str, scene_ids: list[str], model: str,
                 log_dir: str) -> dict[str, dict[str, str]]:
    """Read time cues for *scene_ids* with direct calls in parallel, store
    them in working/timeline-cues.csv, and return them."""
    from .api import invoke_to_file, extract_text
    from .runner import run_parallel
    os.makedirs(log_dir, exist_ok=True)
    prompts = cue_prompts(project_dir, scene_ids)

    def worker(sid):
        response = invoke_to_file(prompts[sid], model,
                                  os.path.join(log_dir, f'timeline-cues-{sid}.json'),
                                  max_tokens=1024, label=f'timeline cues {sid}')
        return parse_cues(extract_text(response))

    results = run_parallel(list(prompts), worker, label='scene')
    cues = {sid: r for sid, r in results.items() if isinstance(r, dict)}
    for sid, r in results.items():
        if not isinstance(r, dict):
            log(f'  WARNING: time cues failed for {sid}: {r}')
    write_cues(project_dir, cues)
    return cues


def check_scenes(project_dir: str, scene_ids: list[str], model: str,
                 log_dir: str) -> list[dict]:
    """Drift check for scenes whose prose changed: read their time cues
    again and compare them with the calendar. Findings for those scenes and
    the scene after each (whose relation to it may have changed) are
    reported and returned; nothing is rewritten, since the prose or the
    calendar may be the one that's wrong."""
    from .elaborate import _read_csv
    if not scene_ids:
        return []
    extract_cues(project_dir, scene_ids, model, log_dir)
    order = reading_order(project_dir)
    touched = set(scene_ids)
    touched.update(order[order.index(s) + 1] for s in scene_ids
                   if s in order and order.index(s) + 1 < len(order))
    rows = {r['id']: r for r in _read_csv(os.path.join(project_dir, 'reference', 'scenes.csv'))}
    findings = [f for f in check_timeline([rows[s] for s in order if s in rows],
                                          read_cues(project_dir))
                if f['scene_id'] in touched]
    report_findings(findings)
    return findings


def drift_check(project_dir: str, scene_ids: list[str]) -> list[dict]:
    """After write or revise: check the scenes whose prose changed against the
    calendar. Skipped when the book has no days yet; never raises, since a
    failed check must not fail the run that called it."""
    from .elaborate import _read_csv
    from .common import select_model
    try:
        rows = _read_csv(os.path.join(project_dir, 'reference', 'scenes.csv'))
        if not scene_ids or not any((r.get('timeline_day') or '').strip() for r in rows):
            return []
        log(f'Timeline drift check: {len(scene_ids)} changed scene(s)')
        return check_scenes(project_dir, scene_ids, select_model('extraction'),
                            os.path.join(project_dir, 'working', 'logs'))
    except Exception as e:  # noqa: BLE001 — advisory only
        log(f'  WARNING: timeline drift check failed: {e}')
        return []


# ============================================================================
# CSV update
# ============================================================================

def apply_timeline_days(assignments: dict[str, int],
                        metadata_csv: str) -> int:
    """Write timeline_day values to scenes.csv. Returns scenes updated."""
    updated = 0
    for scene_id, day_val in assignments.items():
        if update_csv_field(metadata_csv, scene_id, 'timeline_day', str(day_val)):
            updated += 1
    return updated


def report_findings(findings: list[dict], limit: int = 20) -> None:
    if not findings:
        log('  Timeline checks: no inconsistencies')
        return
    log(f'  Timeline checks: {len(findings)} inconsistenc'
        f'{"y" if len(findings) == 1 else "ies"} (reported, not changed)')
    for f in findings[:limit]:
        log(f'    {f["scene_id"]}: {f["message"]}')
    if len(findings) > limit:
        log(f'    (and {len(findings) - limit} more)')
