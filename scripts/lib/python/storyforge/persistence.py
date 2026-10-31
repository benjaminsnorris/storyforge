"""The persistence check: a second question on extracted commitments.

Phase 4's rubric asks three questions of every fact (rethink plan
decision 5), but about four rows in ten it records are still incidental
(the *Carol* re-score at v1.98.0: staging, set dressing, a feeling in the
moment, description inside a vision). A prompt alone didn't get further,
so each scene's proposed commitments go through one more call that asks
only the second question: **does this fact last beyond the scene?**

- `judge(scene_id, prose, found, model=, log_file=)` → `Verdict`:
  `kept` (the entries to record) and `dropped` (entry, why) pairs.
- A commitment that `supersedes` or `ends` another is a change to a fact
  already recorded, so it is kept without asking (`exempt`).
- Called by extract phase 4 and by the gate (`gate._extract`), on the
  parsed reply before it becomes ledger rows. The callers report what was
  dropped: phase 4 logs each with why and totals them, the gate keeps them
  on its result (a NOTE in `report_lines`).
- Fails loud: a refusal, or a reply cut off, off-schema or not answering
  every item exactly once twice running (one retry names what was wrong),
  raises `PersistenceError`.
  There is no partial answer, and no item is dropped by default.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

SCHEMA = {
    'type': 'object',
    'properties': {'verdicts': {'type': 'array', 'items': {
        'type': 'object',
        'properties': {'n': {'type': 'integer'}, 'persists': {'type': 'boolean'},
                       'why': {'type': 'string'}},
        'required': ['n', 'persists', 'why'],
        'additionalProperties': False,
    }}},
    'required': ['verdicts'],
    'additionalProperties': False,
}

PROMPT = """You are reviewing facts extracted from one scene of a novel, to decide which ones a later scene could contradict in a way a careful reader would notice.

## Scene: {scene_id}

{prose}

## Extracted facts

{items}

## The question

For each fact, ask one thing: **does it last beyond this scene?** A reader carries it forward, and a later scene that said otherwise would be a slip.

It lasts (persists: true):
- what happened: an event or a one-off action is part of the story's past once it is over (a meal served, a letter burned, a door bolted that night, who arrived with whom and how). A later scene that says otherwise is a slip;
- what a vision, dream or ghost shows happening or being so (a past event, a future, who is where in it): the story treats it as real;
- a character's possession, clothing, habit or usual place, and an object that could come back (a scarf she always wears, the seat he always takes, a lamp left burning);
- names, spellings, pronouns, ages, dates, how people are related, backstory;
- an injury, an illness, a possession, where a person lives or an object is kept, a state that carries into the next scene;
- who knows what, and who told them;
- counts, distances, travel times, stated rules of the world, institutions;
- the time and day the scene happens, elapsed time stated against another event;
- anything a character promises, threatens or plans;
- a momentary detail that reveals a lasting state (hands shaking because he has been poisoned: the poisoning lasts).

It doesn't (persists: false):
- how something looked or was done in the moment, when nothing later could depend on it: who stands where, which hand holds the cup, a glance, a gesture;
- set dressing and sensory texture the story never returns to: the light, the weather of the moment, the furniture of a room seen once;
- a feeling or reaction in the moment;
- the narrator's opinions and asides;
- figurative language.

Drop only what is clearly incidental. When you are unsure, or a later scene could plausibly call it back, keep it (persists: true): a fact dropped here is a contradiction no one checks later.

Answer with one JSON object: `verdicts`, one entry per fact above, by its number `n`, with `persists` and a short `why`."""


class PersistenceError(RuntimeError):
    """The check could not be completed; the message says why."""


@dataclass
class Verdict:
    kept: list[dict] = field(default_factory=list)
    #: (entry, why) for each fact judged not to last beyond the scene
    dropped: list[tuple[dict, str]] = field(default_factory=list)
    #: entries kept without asking: they supersede or end another fact
    exempt: int = 0
    asked: int = 0


def max_tokens(items: int) -> int:
    """The reply's allowance: room for a verdict and a short why per item,
    so a dense scene isn't cut off (which would halt the chain)."""
    return min(32000, 2000 + 80 * items)


def _is_link(entry: dict) -> bool:
    return bool((entry.get('supersedes') or '').strip() or entry.get('ends'))


def build_prompt(scene_id: str, prose: str, items: list[dict]) -> str:
    lines = '\n'.join(f'{i}. [{e.get("type") or "-"}, {e.get("mutable") or "state"}] '
                      f'{e.get("subject") or "-"}: {e["statement"]}'
                      + (f' — "{e["quote"]}"' if e.get('quote') else '')
                      for i, e in enumerate(items, 1))
    return PROMPT.format(scene_id=scene_id, prose=prose.strip(), items=lines)


def parse(text: str, count: int) -> dict[int, tuple[bool, str]]:
    """The verdicts by item number. Raises ValueError unless every number
    1..count is answered exactly once."""
    try:
        data = json.loads(text)
        verdicts = data['verdicts']
    except (TypeError, ValueError, KeyError) as e:
        raise ValueError(f'reply is not the schema ({e})') from e
    out: dict[int, tuple[bool, str]] = {}
    for v in verdicts:
        if not isinstance(v, dict) or not isinstance(v.get('n'), int) \
                or not isinstance(v.get('persists'), bool):
            raise ValueError(f'a verdict is not the schema: {v!r}'[:200])
        if v['n'] in out:
            raise ValueError(f'item {v["n"]} answered twice')
        out[v['n']] = (v['persists'], str(v.get('why') or '').strip())
    wrong = sorted(set(out) ^ set(range(1, count + 1)))
    if wrong:
        raise ValueError(f'verdicts missing or out of range for item(s) '
                         f'{", ".join(map(str, wrong[:10]))}')
    return out


def judge(scene_id: str, prose: str, found: list[dict], *, model: str,
          log_file: str) -> Verdict:
    """Ask, for each entry of `found` (phase 4's parsed reply) that doesn't
    supersede or end another fact, whether it lasts beyond the scene.
    Order is kept. No entries to ask about: no call.

    Raises:
        PersistenceError: the call failed, was refused or cut off, or the
            reply doesn't answer every item once.
    """
    from storyforge import api
    verdict = Verdict()
    asked = [e for e in found if not _is_link(e)]
    verdict.exempt = len(found) - len(asked)
    verdict.asked = len(asked)
    answers: dict[int, tuple[bool, str]] = {}
    if asked:
        prompt = build_prompt(scene_id, prose, asked)
        for attempt in (1, 2):
            try:
                response = api.invoke_to_file(prompt, model, log_file, max_tokens(len(asked)),
                                              output_schema=SCHEMA,
                                              label=f'persistence {scene_id}')
                if api.is_truncated(response):
                    raise ValueError('the reply hit its token limit')
                answers = parse(api.extract_text(response), len(asked))
                break
            except ValueError as e:
                if attempt == 2:
                    raise PersistenceError(f'{scene_id}: the persistence check failed '
                                           f'twice: {e}') from e
                # One retry, telling the model what was wrong (a reply that
                # skipped items has happened); the request differs, so a
                # recording replays each answer in turn
                prompt = (build_prompt(scene_id, prose, asked)
                          + f'\n\nYour last answer was not usable: {e}. Answer every fact, '
                          f'1 to {len(asked)}, exactly once.')
            except RuntimeError as e:   # RefusalError, an API failure
                raise PersistenceError(f'{scene_id}: the persistence check failed: {e}') from e
    numbers = {id(e): i for i, e in enumerate(asked, 1)}
    for e in found:
        n = numbers.get(id(e))
        if n is None or answers[n][0]:
            verdict.kept.append(e)
        else:
            verdict.dropped.append((e, answers[n][1]))
    return verdict
