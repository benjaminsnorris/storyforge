"""The blocking check: does one scene's physical action hold together? (#626)

The gate's checker (`checker.check_scene`) reports where a scene contradicts
something the book establishes *elsewhere*: another scene, a bible, the
ledger, the calendar. A scene that contradicts itself from one paragraph to
the next, or describes something a body can't do, was out of its scope, and
on *A Year and a Day* (gawain) 35 such slips passed the gate: a right hand on
the thigh "over the knot at his left hip", a beard stroked with a "free hand"
while both hands held holly and an axe, breath warm "on his mouth" through a
closed helm, a clean shirt pulled on over the one he slept in.

This check reads the scene alone, as a line editor tracking bodies and
objects (hands and what they hold, left and right, posture, what is worn,
light, where things are), and reports, with the scene's own words:

- `contradiction`: two places in the scene that can't both be true;
- `impossible`: something a body or an object can't do;
- `unclear`: physical action a reader can't follow (whose hand, who turns).

- `check_blocking(project_dir, scene_id, prose=, model=, log_file=)` →
  `BlockingResult`, its findings as `checker.Finding`s with code
  `BLOCKING_CODE` ('BLK'), kind 'contradiction', and `established_scene`
  the scene itself, so the gate sorts, reports, fixes and accepts them as
  it does the checker's (`gate._classify`: one whose quotes were both in the
  scene before the pass is inherited).
- A finding whose quote isn't in the scene is `unverified`: kept apart,
  never dropped (the gate blocks on it as on the checker's).
- Fails loud: a refusal, a reply cut off or off-schema twice running (one
  retry says what was wrong) raises `BlockingError`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from storyforge.checker import Finding
from storyforge.quotes import quote_in

#: The error code of a blocking finding (beside the checker's `checker.CODES`)
BLOCKING_CODE = 'BLK'

#: Independent readings per check, their findings' union (`check_blocking`).
#: One reading misses most slips another finds: on gawain at a04c452 (#626)
#: one full read flagged 12 of the 35 slips the author's readers fixed and
#: missed his own example, which a second read of that scene found
BLOCKING_READINGS = 2

KINDS = ('contradiction', 'impossible', 'unclear')

SCHEMA = {
    'type': 'object',
    'properties': {'findings': {'type': 'array', 'items': {
        'type': 'object',
        'properties': {
            'kind': {'type': 'string', 'enum': list(KINDS)},
            'scene_quote': {'type': 'string'},
            'other_quote': {'type': 'string'},
            'explanation': {'type': 'string'},
        },
        'required': ['kind', 'scene_quote', 'other_quote', 'explanation'],
        'additionalProperties': False,
    }}},
    'required': ['findings'],
    'additionalProperties': False,
}

PROMPT = """You are a line editor reading one scene of a novel for its blocking: whether the bodies and objects in it stay consistent from sentence to sentence, and whether what they do is physically possible. Nothing else: not style, not plot, not facts from other scenes.

## Scene: {scene_id}{pov_line}

{prose}

## How to read it

Read the scene once through, keeping track as you go of:
- each character's hands: what each hand holds or rests on, and when it lets go (reins, a cup, a weapon, a candle, someone's hand);
- left and right: which hand, which side, who sits on whose left;
- posture: standing, sitting, kneeling, lying, mounted, and the moves between them;
- what each person wears, and what that allows (a closed helm limits sight and touch; gauntlets; armour);
- objects: where each one is, who has it, whether it was put down or picked up;
- light, doors, curtains: lit or out, open or shut.

## What to report

- `contradiction`: two places in the scene that can't both be true, with nothing between them that changes it. A hand that holds something does something else without letting go. Left becomes right. Someone sitting is then standing without getting up. An object is in two places, or set down and still held. A helmet is on, then the face is seen, with no one taking it off. A candle is set down that was never taken up. Quote both places: `scene_quote` the later or the impossible one, `other_quote` the one it contradicts.
- `impossible`: something a body or an object can't do as written, even with no other line against it: a right hand resting on the right thigh while touching the left hip; breath felt on the mouth through a closed helm; seeing what can't be seen from where someone is; a shoulder coming away "under the hide" after the hide is off. `other_quote` is the line that makes it impossible, or empty if the sentence alone shows it.
- `unclear`: physical action a reader can't follow, where the words leave it open who or what moves ("Then he turned him."). `other_quote` empty.

## What not to report

- A change the scene shows, however briefly ("he set the cup down and took her hand").
- Movement a reader assumes between paragraphs or across a gap in time.
- Figurative language, memory, dreams, and what a character imagines.
- Anything plausible: reaching across the body when the text says so, a lance resting in its socket while he crosses himself. When in doubt, leave it out: a false report costs the author more than a miss.
- Anything about other scenes, the plot, style or word choice.

Copy every quote exactly from the scene, a clause or a sentence, long enough to find it. Explain each finding in one or two sentences, saying what can't be so and why. Return every finding, and an empty list when the blocking holds."""


class BlockingError(RuntimeError):
    """The blocking check could not be completed; the message says why."""


@dataclass
class BlockingResult:
    scene_id: str
    findings: list[Finding] = field(default_factory=list)
    unverified: list[Finding] = field(default_factory=list)


def build_prompt(scene_id: str, prose: str, pov: str = '', reading: int = 1) -> str:
    """The prompt; a reading after the first says which it is, so it is its
    own request (recordings are keyed by the request)."""
    pov_line = f'\n\nPoint of view: {pov}' if pov.strip() else ''
    text = PROMPT.format(scene_id=scene_id, pov_line=pov_line, prose=prose.strip())
    if reading > 1:
        text += (f'\n\nThis is independent reading {reading} of this scene: read it fresh, '
                 f'from the first line.')
    return text


def _same(a: Finding, b: Finding) -> bool:
    """Two readings' findings on one slip: one's scene quote holds the
    other's, or they quote the same pair of lines."""
    from storyforge.quotes import normalize
    x, y = normalize(a.scene_quote), normalize(b.scene_quote)
    if x and y and (x in y or y in x):
        return True
    return ({x, normalize(a.established_quote)} == {y, normalize(b.established_quote)})


def parse(text: str) -> list[dict[str, str]]:
    """The reply's findings. Raises ValueError when it isn't the schema."""
    try:
        data = json.loads(text)
        items = data['findings']
    except (TypeError, ValueError, KeyError) as e:
        raise ValueError(f'reply is not the schema ({e})') from e
    if not isinstance(items, list):
        raise ValueError('findings is not a list')
    out = []
    for item in items:
        if (not isinstance(item, dict) or item.get('kind') not in KINDS
                or not all(isinstance(item.get(k), str)
                           for k in ('scene_quote', 'other_quote', 'explanation'))):
            raise ValueError(f'a finding is not the schema: {item!r}'[:200])
        out.append(item)
    return out


def to_finding(scene_id: str, prose: str, item: dict[str, str]) -> Finding:
    """One reply item as a `checker.Finding` (code `BLOCKING_CODE`), its
    `problem` set when a quote isn't in `prose`. A finding with no second
    quote names its own sentence as what it is set against, so
    `gate._classify` can tell whether it was in the scene before."""
    scene_quote = item['scene_quote'].strip()
    other = item['other_quote'].strip()
    problem = ''
    if not scene_quote:
        problem = 'it quotes nothing from the scene'
    elif not quote_in(prose, scene_quote):
        problem = 'its scene quote is not in the scene'
    elif other and not quote_in(prose, other):
        problem = 'its second quote is not in the scene'
    elif item['kind'] == 'contradiction' and not other:
        problem = 'a contradiction with only one side quoted'
    return Finding(kind='contradiction', code=BLOCKING_CODE, scene_quote=scene_quote,
                   established_scene=scene_id, established_quote=other or scene_quote,
                   fact_id='', explanation=f'({item["kind"]}) {item["explanation"].strip()}',
                   problem=problem)


def _scene_prose(project_dir: str, scene_id: str) -> str:
    from storyforge.illustrations import read_scene_raw
    text = read_scene_raw(project_dir, scene_id)   # the gate exception (docs/history.md)
    if not (text or '').strip():
        raise BlockingError(f'{scene_id} has no prose to check')
    return text


def _pov(project_dir: str, scene_id: str) -> str:
    import os
    from storyforge.elaborate import _read_csv_as_map
    try:
        rows = _read_csv_as_map(os.path.join(project_dir, 'reference', 'scenes.csv'))
    except OSError:
        return ''
    return (rows.get(scene_id, {}).get('pov') or '').strip()


def max_tokens(prose: str) -> int:
    """Room for a dense scene's findings: a few hundred words each."""
    return min(16000, 3000 + len(prose.split()) * 2)


def check_blocking(project_dir: str, scene_id: str, *, prose: str | None = None,
                   model: str | None = None, log_file: str = '',
                   readings: int | None = None) -> BlockingResult:
    """Read `scene_id`'s blocking (its file, or `prose` in its place),
    `readings` times (default `BLOCKING_READINGS`), one after the other, and
    return their union: reading 1's findings, then each later reading's that
    no earlier one made (`_same`). Reading n > 1 logs to `log_file` with
    `.rN` before its extension.

    Raises:
        BlockingError: no prose, a refusal or API failure, or a reply cut off
            or off-schema twice running, in any reading.
        ValueError: `readings` below 1.
    """
    import os
    from storyforge.common import select_model
    readings = BLOCKING_READINGS if readings is None else readings
    if readings < 1:
        raise ValueError(f'readings must be at least 1, not {readings}')
    text = prose if prose is not None else _scene_prose(project_dir, scene_id)
    if not text.strip():
        raise BlockingError(f'{scene_id} has no prose to check')
    model = model or select_model('checking')
    pov = _pov(project_dir, scene_id)
    result = BlockingResult(scene_id)
    for n in range(1, readings + 1):
        log = log_file
        if n > 1 and log_file:
            stem, ext = os.path.splitext(log_file)
            log = f'{stem}.r{n}{ext}'
        for f in _read_once(scene_id, text, pov, model, log, n):
            known = result.findings + result.unverified
            if any(_same(f, k) for k in known):
                continue
            (result.unverified if f.problem else result.findings).append(f)
    return result


def _read_once(scene_id: str, text: str, pov: str, model: str, log_file: str,
               reading: int) -> list[Finding]:
    """One reading's findings, verified or not (`to_finding`)."""
    from storyforge import api
    prompt = build_prompt(scene_id, text, pov, reading)
    items: list[dict[str, str]] = []
    for attempt in (1, 2):
        try:
            if log_file:
                response = api.invoke_to_file(prompt, model, log_file, max_tokens(text),
                                              output_schema=SCHEMA,
                                              label=f'blocking {scene_id}')
            else:
                response = api.invoke(prompt, model, max_tokens(text), output_schema=SCHEMA,
                                      label=f'blocking {scene_id}')
            if api.is_truncated(response):
                raise ValueError('the reply hit its token limit')
            items = parse(api.extract_text(response))
            break
        except ValueError as e:
            if attempt == 2:
                raise BlockingError(f'{scene_id}: the blocking check failed twice: {e}') from e
            prompt = (build_prompt(scene_id, text, pov, reading)
                      + f'\n\nYour last answer was not usable: {e}. Answer in the schema.')
        except RuntimeError as e:   # RefusalError, an API failure
            raise BlockingError(f'{scene_id}: the blocking check failed: {e}') from e
    return [to_finding(scene_id, text, item) for item in items]
