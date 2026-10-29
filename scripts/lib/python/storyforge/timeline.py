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
from .elaborate import OFF_PRESENT_MODES
from .enrich import update_csv_field


RELATIONS = ('continues', 'later', 'earlier', 'frame', 'vision', 'unclear')
TIME_MODES = ('scene', 'summary', 'frame', 'vision')

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

CUE_INSTRUCTIONS = """TIME_RELATION: [when this scene happens relative to the scene before it in reading order — one of: continues (picks up at the same time or moments later), later (some time after it), earlier (before it: a flashback or a recollection told as a scene, including a past that a spirit, dream or vision shows a character; also a scene whose present is only a line or a short lead-in before it mostly tells the past, such as a story a character tells or the narrator's account of someone's youth, but not one where the present has real action on the page around the telling), frame (narration from after the story, looking back), vision (events that have not happened, or may not happen, as the story tells them: a prophecy, a future a character is shown that may be averted, a dream of what might come; the past is always earlier, even when a spirit, a dream or a vision shows it), unclear]
TIME_GAP: [the gap from the previous scene in at most six words, no explanation: "an hour", "the next morning", "three weeks", "five years", "several weeks"; empty if none is stated or implied]
TIME_ANCHOR: [a calendar fact pinning when THIS scene's action happens — a date, weekday, month, season, holiday or named day ("the hottest day of the summer") — quoted briefly; not a habit ("every Friday") or a date the scene only mentions; empty if none]
TIME_REFERS: [any statement in this scene of how long ago or how long until another event in the story, quoted briefly: "that June night three months before", "five years since he'd seen her", "the funeral was on the third day"; separate several with semicolons; empty if none]
TIME_SPAN: [when the scene summarizes a stretch of time ("all that summer"), how long; empty for a scene that plays out in one sitting]
TIME_DATE: [only what this scene's own text states about the calendar date, in EDTF: "1922-07-04", "XXXX-07-04" when the year isn't given here, "1922" for a year, "1922-22" for summer 1922 (21 spring, 22 summer, 23 autumn, 24 winter), "1917~" for "around 1917", "1922-06/1922-09" for a stretch. A date the text fixes by a stated distance from a named calendar day counts as given, marked ~: "In two weeks it'll be the longest day in the year" → "XXXX-06-07~". Never fill in a part the text doesn't give; empty if the text gives no date]"""

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
    # An explanation, not a gap: a phrase picked out of it would be a guess.
    # A bracketed or quoted aside marks one too: 'three days" (vacation
    # between terms)' was a vacation's length, not the gap (F-066)
    if not text or len(text.split()) > 8 or re.search(r'[()"]', text):
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


def _day_of_year(month: int, day: int) -> int:
    """Day of the year on 2001's calendar (February 29 counts as the 28th)."""
    from datetime import date
    try:
        return date(2001, month, day).timetuple().tm_yday
    except ValueError:
        return date(2001, month, 28).timetuple().tm_yday


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
        words.append(str(int(day)) if month and 'X' not in month
                     else f'day {int(day)} of an unstated month')
    if month and 'X' not in month:
        mi = int(month)
        words.append(_SEASONS.get(mi) or _MONTHS[mi - 1])
    year_text = year if 'X' not in year else ('' if year == 'XXXX' else year.replace('X', '?'))
    text = ' '.join(words + ([year_text] if year_text else [])).strip()
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


# Where in the year a month or season falls: (day of year at its middle,
# half its length), on 2001's calendar
_SEASON_SPANS = {21: (105, 46), 22: (197, 46), 23: (289, 45), 24: (15, 45)}
# Slack on top of the two spans: "early in May" on the 2nd is still May
_ROUGH_SLACK = 7


def _rough_date(value: str) -> tuple[int, int, str] | None:
    """``(day of year, half-width, words)`` for a single date with a known
    month or season but no known day (``XXXX-05``, ``1922-22~``), else None.
    Its year doesn't count: only where in the year it falls."""
    m = _EDTF_DATE.match((value or '').strip())
    if not m or not m.group('month') or 'X' in m.group('month'):
        return None
    if m.group('day') and 'X' not in m.group('day'):
        return None
    month = int(m.group('month'))
    if month in _SEASON_SPANS:
        middle, half = _SEASON_SPANS[month]
        return middle, half, _SEASONS[month]
    if not 1 <= month <= 12:
        return None
    return _day_of_year(month, 15), 15, _MONTHS[month - 1]


# ============================================================================
# Assignment: the running-present walk, then batches
# ============================================================================

def walk(order: list[str], cues: dict[str, dict], last: int | None = None,
         present: int | None = None) -> dict[str, int | None]:
    """Provisional days from the cues alone, in reading order.

    A scene is placed relative to the previous scene: ``continues`` on its
    day, ``later``/``earlier`` by a parseable gap; a vision is placed like a frame. After a flashback scene a
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
        # A vision, like a frame, is off the story's clock: the scene after
        # it is read against the scene before it (Scrooge wakes "moments
        # later" in his own night, not in the future he was shown)
        if relation in OFF_PRESENT_MODES:
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
- A recollection told inside a present scene is placed by weight, the same way every time: if the present frame is a line or a short lead-in and the page mostly tells the past, the scene gets the remembered day; if the present has real action on the page around the telling, it gets the present day. Follow an "earlier" cue unless the summary shows real present action.
- frame: narration from after the story; it gets the day it is narrated from (after the story's end, roughly) and does not move the present.
- vision: events that have not happened, or may not happen (a future a character is shown that may be averted, a prophecy); it gets the day it shows if the text fixes one, otherwise the viewer's day, and does not move the present. The scene after a vision continues from the scene before it. The past is never a vision: a past shown by a spirit or a dream is earlier and gets its past day.
- Fix the calendar first: from the dates, months, holidays and named days in the cues (including "refers" cues such as "that June night"), work out which calendar date day 1 falls on, and say so. Then turn every such anchor into a day by counting from day 1's date: with day 1 on June 7, "a few days before the Fourth of July" is about day 25 and "late in July" about day 45-55. Vague gaps give way to these.
- A date anchor pins a scene: keep dates consistent with the days between them. Weekdays are weak evidence (characters misname days, and "Saturday" may be a day mentioned rather than the scene's own): use them where they agree, and where they conflict, drop them rather than work them out.
- "refers" cues state how far apart two events are ("that June night three months before" puts this scene about 90 days after that night). They are the firmest evidence of distance: where vague gaps ("several weeks", "some time later") add up to something else, stretch or shrink the vague gaps to fit the stated durations, counting back as well as forward.
- mode: scene (the action plays out on its day), summary (it covers a stretch of time; the day is where the stretch starts), frame, or vision.

{"Write a line CALENDAR: and nothing before it; after it" if terse else "First work out the calendar under a line REASONING: — give day 1's calendar date, list the anchors and every stated duration (refers), fix the days they pin, then fit the vague gaps between them; note any scene you are unsure of — in at most 600 words. Then write a line CALENDAR: and, after it,"} exactly one line per scene, in order:

scene_id | day | mode | basis

basis: a few words on why ("next morning", "anchor: July 4", "1917, five years before"). Nothing after the calendar lines."""


def parse_assignments(response: str, ids: list[str]) -> dict[str, tuple[int, str, str]]:
    """Parse ``scene_id | day | mode | basis`` lines for the scenes in *ids*.

    Days may be zero or negative. ``earlier`` given as the mode means
    ``scene``; a missing or unknown mode comes back as ``''`` for the
    caller to decide. Lines for other ids or with a
    non-integer day are ignored.
    """
    wanted = set(ids)
    result: dict[str, tuple[int, str, str]] = {}
    # Only the answer after CALENDAR: counts; reasoning above it may try out
    # days it then revises
    text = response or ''
    # The last marker, wherever the answer starts: "CALENDAR: a | 5 | ..."
    # or "**CALENDAR:**" on its own line
    markers = list(re.finditer(r'^\W*CALENDAR:\W*?(?=\w|$)', text, re.MULTILINE))
    if markers:
        text = text[markers[-1].end():]
    for line in text.split('\n'):
        parts = [p.strip() for p in line.strip().lstrip('-* ').split('|')]
        if len(parts) < 2 or parts[0] not in wanted:
            continue
        try:
            day = int(parts[1].lstrip('+'))
        except ValueError:
            continue
        raw = parts[2].lower() if len(parts) > 2 else ''
        # "earlier" in the mode column still says the scene is on the story's
        # clock: Carol's Stave II came back "| -18250 | earlier |", and
        # falling back on its "vision" cue hid the past. Only "earlier": a
        # "later" could be a frame or vision line that lost its mode
        mode = raw if raw in TIME_MODES else 'scene' if raw == 'earlier' else ''
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
            if text is None:
                log(f'  WARNING: {label} gave no calendar; its scenes keep their provisional days')
        answers = parse_assignments(text, [it['id'] for it in batch]) if text is not None else {}
        for it in batch:
            sid = it['id']
            cue = it.get('cues', {})
            if sid in answers:
                day, mode, basis = answers[sid]
                # A line that lost its mode column ("id | 800 | frame
                # narration") must not make a frame the story's present
                if not mode:
                    mode = cue.get('relation') if cue.get('relation') in OFF_PRESENT_MODES else 'scene'
                placed[sid] = (day, mode, basis)
            elif it['provisional'] is not None:
                placed[sid] = (it['provisional'], 'scene', 'from cues')
            if sid not in placed:
                continue
            day, mode, _basis = placed[sid]
            if mode not in OFF_PRESENT_MODES:
                last_day = day
                if cue.get('relation') != 'earlier' and (present is None or day > present):
                    present = day
            for key in ('anchor', 'refers', 'date'):
                if cue.get(key):
                    shown = describe_edtf(cue[key]) if key == 'date' else cue[key]
                    anchors.append(f'{sid}: day {day} — {shown}')
    return placed


# ============================================================================
# Month anchors: code pins what the model miscounts
# ============================================================================

# The model reads "early in May" right but counts days from it wrong (The
# Plastic Age: junior year opened on day 730 in September, and the prom
# "early in May" came out day 848, about January; F-071). Code finds where
# day 1 falls in the year from the anchors that agree, then moves each run
# of scenes whose anchor disagrees into its month, taking up the difference
# in a vague gap ("some weeks later") and never in a stated one.

_MONTH_NAMES = r'January|February|March|April|May|June|July|August|September|October|November|December'
_QUALIFIER = r'(?:(?P<q>[Ee]arly|[Ll]ate|[Mm]id(?:dle)?)(?:-|\s+)(?:(?:in|of)\s+)?(?:the\s+)?)?'
# Case matters: "may" is a verb, and a capital Fall is the season
_ANCHOR_MONTH = re.compile(_QUALIFIER + r'\b(?P<m>' + _MONTH_NAMES + r')\b')
# "Indian summer" is autumn weather, not summer
_ANCHOR_SEASON = re.compile(_QUALIFIER + r'(?<![Ii]ndian )\b(?P<s>[Ss]pring|[Ss]ummer|[Aa]utumn|Fall|[Ww]inter)\b')
# First day (0 = January 1) and length of each season
_SEASON_RANGES = {'spring': (59, 92), 'summer': (151, 92), 'autumn': (243, 91), 'winter': (334, 90)}
_MONTH_LENGTHS = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
# An anchor within a week of its month counts as kept; a season's edges are
# looser ("autumn flavour in the air" in Gatsby's mid-August)
PIN_SLACK = 7
SEASON_SLACK = 21
# A month the anchor says belongs to a memory is not the scene's own:
# Gatsby's dawn scene, "that still October night (in the flashback)"
_REMEMBERED = re.compile(r'flashback|memory|recall|remember', re.I)
# A month the anchor places at another time than the scene's: "planning to
# marry next June", "last spring", "since March"
_OTHER_TIME = re.compile(r'\b(next|last|previous|since|ago|until|till)\b', re.I)
# A name, not a month: "Aunt May", "Miss June"
_NAMED = re.compile(r'\b(Aunt|Uncle|Miss|Mrs?|Ms|Lady|Sir|Dr)\.?\s+$')


def anchor_window(anchor: str) -> tuple[int, int, str, int] | None:
    """``(first, last, words, slack)``: the days of the year (0 = January 1;
    ``last`` may be below ``first`` across the new year) that a cue's anchor
    puts the scene in, from one month or one season, with "early", "mid" or
    "late", and how far outside them still counts. None when it names none,
    or more than one (a month wins over a season), or says it is remembered."""
    text = anchor or ''
    if _REMEMBERED.search(text) or _OTHER_TIME.search(text):
        return None
    found = {(m.group('q') or '', m.group('m')) for m in _ANCHOR_MONTH.finditer(text)
             if not _NAMED.search(text[:m.start('m')])}
    if found:
        if len({m for _q, m in found}) != 1 or len(found) != 1:
            return None
        qual, name = found.pop()
        month = _MONTH_NAMES.split('|').index(name)
        start, length = sum(_MONTH_LENGTHS[:month]), _MONTH_LENGTHS[month]
        part = {'early': (0, 10), 'mid': (10, 10), 'middle': (10, 10), 'late': (20, length - 20)}
        slack = PIN_SLACK
    else:
        found = {(m.group('q') or '', m.group('s').lower().replace('fall', 'autumn'))
                 for m in _ANCHOR_SEASON.finditer(text)}
        if len(found) != 1:
            return None
        qual, name = found.pop()
        start, length = _SEASON_RANGES[name]
        third = length // 3
        part = {'early': (0, third), 'mid': (third, third), 'middle': (third, third),
                'late': (length - third, third)}
        slack = SEASON_SLACK
    offset, span = part.get(qual.lower(), (0, length))
    words = f'{qual.lower()} {name}'.strip()
    return (start + offset) % 365, (start + offset + span - 1) % 365, words, slack


def _distance(doy: int, window: tuple[int, int, str, int]) -> tuple[int, int]:
    """Days forward to *window*'s first day and back to its last; (0, 0)
    when *doy* is inside it."""
    first, last, _words, _slack = window
    inside = first <= doy <= last if first <= last else (doy >= first or doy <= last)
    if inside:
        return 0, 0
    return (first - doy) % 365, (doy - last) % 365


def _present_entries(items: list[dict], placed: dict[str, tuple[int, str, str]]):
    """The story's present in reading order, as ``(entries, riders)``.

    Each entry: id, day, stated (joined to the entry before it by
    "continues" or a stated gap) and window (its month or season anchor, on
    a scene shown as it happens). *riders* maps an entry to the flashback
    scenes told after it. Frames and visions are left out; flashbacks are
    read by relation, as walk() reads them, not by day: one overshoot (the
    prom on day 848) must not make every scene after it a flashback.
    """
    entries = []
    # Flashback scenes (and what continues them) ride along with the present
    # scene before them: a memory "three weeks earlier" keeps its distance
    riders: dict[str, list[str]] = {}
    in_flashback = False
    for it in items:
        sid = it['id']
        if sid not in placed:
            continue
        day, mode, _basis = placed[sid]
        cue = it.get('cues', {})
        relation = cue.get('relation') or 'unclear'
        if mode in OFF_PRESENT_MODES:
            continue
        in_flashback = relation == 'earlier' or (in_flashback and relation == 'continues')
        if in_flashback:
            if entries:
                riders.setdefault(entries[-1]['id'], []).append(sid)
            continue
        stated = relation == 'continues' or (relation == 'later' and gap_to_days(cue.get('gap', '')) is not None)
        window = anchor_window(cue.get('anchor', '')) if mode == 'scene' else None
        entries.append({'id': sid, 'day': day, 'mode': mode, 'stated': stated and bool(entries),
                        'window': window})
    return entries, riders


def _runs(entries: list[dict]) -> list[list[dict]]:
    """Entries grouped into runs: scenes joined by "continues" or a stated
    gap move together; a vague gap starts a new run."""
    runs: list[list[dict]] = []
    for e in entries:
        if e['stated'] and runs:
            runs[-1].append(e)
        else:
            runs.append([e])
    return runs


def pin_month_anchors(items: list[dict], placed: dict[str, tuple[int, str, str]]):
    """Move scenes whose anchor names a month or season the calendar puts
    them out of. Returns ``(placed, moves, day_one)``: the new placements,
    ``(scene id, old day, new day, anchor words)`` per scene moved, and day
    1's day of the year (None when there are too few anchors to tell).

    *items* are in reading order. Only the story's present anchors; a
    flashback moves with the present scene before it, and frames and
    visions keep their days. Scenes joined by "continues" or
    a stated gap move together; a scene after a vague gap is where a run
    starts, and the vague gap takes up the move. A later run moves only as
    far as it must to stay after the one before. Only a scene shown as it
    happens (mode scene, not a summary) anchors.
    """
    entries, riders = _present_entries(items, placed)
    anchored = [e for e in entries if e['window']]
    if len(anchored) < 2:
        return placed, [], None

    # Day 1's day of the year: the one that keeps the most anchors, a month
    # counting as three seasons (a season's loose edges let a wrong calendar
    # keep as many: The Plastic Age fitted November with equal weights), then
    # the one nearest their middles, so a run of equally good days resolves
    # to its centre rather than its first
    def weight(window):
        return 1 if window[3] == SEASON_SLACK else 3

    def from_middle(doy, window):
        first, last = window[0], window[1]
        middle = (first + ((last - first) % 365) // 2) % 365
        return min((doy - middle) % 365, (middle - doy) % 365)

    def fit(day_one):
        kept = total = 0
        for e in anchored:
            doy = (day_one + e['day'] - 1) % 365
            if min(_distance(doy, e['window'])) <= e['window'][3]:
                kept += weight(e['window'])
            total += from_middle(doy, e['window'])
        return kept, -total
    day_one = max(range(365), key=fit)
    if fit(day_one)[0] * 2 < sum(weight(e['window']) for e in anchored):
        # Most anchors disagree with any one calendar: the anchors, not the
        # days, are what's wrong
        return placed, [], None

    runs = _runs(entries)
    moves = []
    new_day = {}
    prev_end = prev_old_end = None
    prev_shift = 0
    floor = min(1, min(e['day'] for e in entries))
    for run in runs:
        # A run the move pushed into goes on only as far as order needs: the
        # gaps after a misplaced anchor were sized against the wrong
        # calendar too, so keeping them would carry the error on (The
        # Plastic Age's track meet went from June to July)
        # Only a push this code caused: where the model itself put a later
        # scene on an earlier day, a push would carry its error a year on
        shift = 0
        if prev_end is not None and run[0]['day'] < prev_end and prev_shift > 0:
            shift = min(prev_end + 1 - run[0]['day'], prev_shift)
        for e in run:
            if not e['window']:
                continue
            doy = (day_one + e['day'] + shift - 1) % 365
            forward, back = _distance(doy, e['window'])
            if min(forward, back) <= e['window'][3]:
                continue
            if back < forward:
                # Back only as far as the run before it (or day 1) allows;
                # never the long way round instead, which adds a year
                lowest = prev_end if prev_end is not None else floor
                step = -back if run[0]['day'] + shift - back >= lowest else 0
            else:
                step = forward
            # Every other anchor in the run must still hold
            if step and all(min(_distance((day_one + o['day'] + shift + step - 1) % 365, o['window']))
                            <= o['window'][3] for o in run if o['window'] and o is not e):
                shift += step
            break
        # A flashback inside the stretch that moved goes with it; one to
        # before it (freshman year recalled in junior year) stays
        since = prev_old_end if prev_old_end is not None else run[0]['day']
        for e in run:
            near = [r for r in riders.get(e['id'], []) if placed[r][0] > since]
            for sid in [e['id']] + near:
                old = placed[sid][0]
                new_day[sid] = old + shift
                if shift:
                    moves.append((sid, old, old + shift,
                                  e['window'][2] if e['window'] and sid == e['id'] else ''))
        prev_end, prev_old_end, prev_shift = run[-1]['day'] + shift, run[-1]['day'], shift
    pinned = {sid: (new_day.get(sid, day), mode, basis) for sid, (day, mode, basis) in placed.items()}
    return pinned, moves, day_one


# A run this far ahead of both runs around it, which agree with each other,
# is out of reading order (F-072)
SPIKE_DAYS = 30
_YEARS = re.compile(r'\b(years?|decades?)\b', re.I)


def repair_spikes(items: list[dict], placed: dict[str, tuple[int, str, str]]):
    """Put back a run the model placed far ahead of both its neighbours.
    Returns ``(placed, moves)``, moves as ``(scene id, old day, new day)``.

    The story's present runs in reading order, so a run more than
    SPIKE_DAYS after the run before it *and* the run after it, where those
    two agree, is a miscount (The Plastic Age's freshman exams on day 900,
    between days 161 and 270). Only scenes count as neighbours: a summary's
    day is where its stretch starts, not where the story stands. It goes between them: a stated gap from the
    run before, else halfway. Only forward spikes: a scene far behind both
    may be a flashback its cue missed, and is left to the checks. Left alone
    too: a jump the cue explains in years ("Years later"), a run wider than
    the room between its neighbours, and two spikes in a row (each is the
    other's neighbour; the checks report them). A flashback told inside the
    run moves with it if it remembers the spike's stretch (after the next
    run's day).
    """
    entries, riders = _present_entries(items, placed)
    runs = _runs(entries)
    cues = {it['id']: it.get('cues', {}) for it in items}
    moves = []
    new_day: dict[str, int] = {}
    for i, run in enumerate(runs):
        # Neighbours are scenes: a summary's day is where its stretch starts,
        # so one may step back in reading order (The Plastic Age's season
        # of football, from October 1, told after the smoker before the big
        # game) and one ahead of a scene may cover weeks
        before = next((r for r in reversed(runs[:i]) if r[-1]['mode'] == 'scene'), None)
        after = next((r for r in runs[i + 1:] if r[0]['mode'] == 'scene'), None)
        if before is None or after is None:
            continue
        lo = new_day.get(before[-1]['id'], before[-1]['day'])
        hi = after[0]['day']
        first, last = min(e['day'] for e in run), max(e['day'] for e in run)
        if not (first > lo + SPIKE_DAYS and first > hi + SPIKE_DAYS and hi >= lo):
            continue
        cue = cues[run[0]['id']]
        # A jump the text explains is not a miscount: "Years later" with no
        # count of years is still a flash-forward
        if _YEARS.search(' '.join(cue.get(k, '') for k in ('gap', 'anchor', 'span'))):
            continue
        # A run wider than the room between its neighbours can't go back
        # without overrunning the next one
        span = last - first
        if span > hi - lo:
            continue
        gap = gap_to_days(cue.get('gap', ''))
        target = min(lo + gap, hi) if gap is not None else (lo + hi) // 2
        target = max(lo, min(target, hi - span))
        shift = target - first
        for e in run:
            # A memory of the spike's own stretch (past the next run) moves
            # with it; one of the ordinary story time between its
            # neighbours, or before, stays
            near = [r for r in riders.get(e['id'], []) if placed[r][0] > hi]
            for sid in [e['id']] + near:
                old = placed[sid][0]
                new_day[sid] = old + shift
                moves.append((sid, old, old + shift))
    repaired = {sid: (new_day.get(sid, day), mode, basis) for sid, (day, mode, basis) in placed.items()}
    return repaired, moves


# ============================================================================
# Checks (deterministic; reported, never applied)
# ============================================================================

_WEEKDAYS = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']


def _int(value) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


# Weekdays are compared only between scenes at most this many days apart
WEEKDAY_SPAN = 31
# Narrow on purpose: "Saturday, the day after the party" is still Saturday
_OTHER_DAY = re.compile(r'\b(to-?morrow|yesterday)\b')


def check_timeline(scenes: list[dict], cues: dict[str, dict]) -> list[dict]:
    """Inconsistencies between days, modes, cues and dates.

    *scenes*: scenes.csv rows in reading order. Returns findings
    ``{'scene_id', 'check', 'message'}``. Checks: the present going
    backwards on a scene not told as earlier and not a frame or vision; a stated gap
    the days disagree with; two dates, two months or seasons, or two weekdays,
    the days contradict.
    """
    findings = []
    present = None
    last_day = None
    last_mode = ''
    after_frame = False
    dated: list[tuple[str, int, tuple]] = []
    rough: list[tuple[str, int, tuple]] = []
    weekdays: list[tuple[str, int, int]] = []
    for row in scenes:
        sid = row.get('id', '')
        day = _int(row.get('timeline_day'))
        mode = (row.get('time_mode') or 'scene').strip() or 'scene'
        cue = cues.get(sid, {})
        relation = cue.get('relation', '')
        if mode in OFF_PRESENT_MODES:
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
        # A step back from the present must go back. Inside a flashback an
        # "earlier" cue may move on through the past (Carol's Stave II runs
        # from Scrooge's boyhood to Belle's family), but not out of it
        if relation == 'earlier' and last_day is not None and (
                day >= last_day if at_present else day >= present):
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
            rough.append((sid, day, (_day_of_year(md[1], md[2]), 0, f'{md[2]} {_MONTHS[md[1] - 1]}')))
        elif mode == 'scene' and _rough_date(row.get('timeline_date', '')):
            # A month or season, on a scene that happens on one day: a
            # summary's date may be the end of its stretch, not its start
            rough.append((sid, day, _rough_date(row['timeline_date'])))
        anchor = (cue.get('anchor') or '').lower()
        named = [i for i, w in enumerate(_WEEKDAYS) if re.search(rf'\b{w}s?\b', anchor)]
        # One weekday, on a scene that happens on one day: a summary's
        # "Sunday mornings" is a habit, not a date
        weekday = named[0] if len(named) == 1 and mode == 'scene' else None
        # A weekday beside "to-morrow" or "yesterday" is another day's: the
        # smoker "the day after to-morrow" before "Saturday afternoon"'s game
        # is not on Saturday (F-068)
        if weekday is not None and _OTHER_DAY.search(anchor):
            weekday = None
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
            between = same_year = (date(year, m2, dd2) - date(year, m1, dd1)).days
            # With the year unstated, December 30 then January 2 may
            # simply cross into the next year
            if 'X' in y1 and between < 0:
                between = (date(year + 1, m2, dd2) - date(year, m1, dd1)).days
        except ValueError:
            continue
        if abs(between - (d2 - d1)) > 1:
            # A year-less date that steps back reads as going back, with the
            # turn of the year as the other reading: Carol's Christmas Eve
            # after Christmas Day isn't "364 days after" (F-059)
            if between != same_year:
                message = (f'its date ({dd2} {_MONTHS[m2 - 1]}) is {-same_year} day(s) before '
                           f'{s1}\'s ({dd1} {_MONTHS[m1 - 1]}), or {between} day(s) after if the '
                           f'year turned, but its day is {d2 - d1} day(s) after')
            else:
                message = (f'its date is {between} day(s) after {s1}\'s, '
                           f'but its day is {d2 - d1} day(s) after')
            findings.append({'scene_id': s2, 'check': 'date_mismatch', 'message': message})
    # A month or a season against the dated scene before it: the year is
    # unstated or too rough to count, so any whole number of years may lie
    # between, but the days must land in the right part of the year (The
    # Plastic Age's prom "early in May", 290 days after a March, F-070)
    for (s1, d1, (y1, h1, w1)), (s2, d2, (y2, h2, w2)) in zip(rough, rough[1:]):
        if not (h1 or h2):
            continue
        actual = d2 - d1
        years = round((actual - (y2 - y1)) / 365)
        expected = y2 - y1 + 365 * years
        if abs(actual - expected) > h1 + h2 + _ROUGH_SLACK:
            ahead = (y2 - y1) % 365
            findings.append({'scene_id': s2, 'check': 'date_mismatch',
                             'message': f'its date ({w2}) falls about {ahead} day(s) after '
                                        f'{s1}\'s ({w1}) in the year, or a whole number of years '
                                        f'more, but its day is {actual} day(s) after'})
    for (s1, d1, w1), (s2, d2, w2) in zip(weekdays, weekdays[1:]):
        # Over months the days are too rough for weekday arithmetic: a
        # Thursday 884 days after a Saturday says nothing (F-067)
        if abs(d2 - d1) > WEEKDAY_SPAN:
            continue
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
            log(f'  WARNING: {label} failed ({e})')
            return None
        if is_truncated(response):
            log(f'  WARNING: {label} hit the {_BATCH_MAX_TOKENS}-token limit')
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
    placed, spikes = repair_spikes(items, placed)
    if spikes:
        log(f'  Timeline: {len(spikes)} scene(s) far ahead of the scenes around them put back:')
        for sid, old, new in spikes:
            log(f'    {sid}: day {old} -> {new}')
    placed, moves, _day_one = pin_month_anchors(items, placed)
    if moves:
        anchors = [m for m in moves if m[3]]
        log(f'  Timeline: {len(moves)} scene(s) moved so {len(anchors)} month anchor(s) hold:')
        for sid, old, new, words in moves:
            log(f'    {sid}: day {old} -> {new}' + (f' ({words})' if words else ''))

    scenes_path = os.path.join(project_dir, 'reference', 'scenes.csv')
    rows = _read_csv(scenes_path)
    # A calendar is one piece: where the author has set any day, a new one
    # is only proposed, never mixed in (its days may be offset from theirs)
    authored = any((r.get('timeline_day') or '').strip() for r in rows if r.get('id') in placed)
    write = force or not authored
    if not write:
        # Proposals are made on the author's calendar: where they counted
        # day 1 differently, a constant offset is not a disagreement
        # (shared-dark: 81 of 100 days 'differed', mostly by one shift)
        offsets = sorted(placed[r['id']][0] - _int(r['timeline_day']) for r in rows
                         if r.get('id') in placed and _int(r.get('timeline_day')) is not None
                         and placed[r['id']][1] not in OFF_PRESENT_MODES)
        shift = offsets[len(offsets) // 2] if offsets else 0
        if shift:
            placed = {sid: (day - shift, mode, basis) for sid, (day, mode, basis) in placed.items()}
            log(f'  Timeline: proposals aligned to your calendar (shifted {-shift:+d} days)')
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
