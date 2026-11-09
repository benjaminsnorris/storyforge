"""Narrow yes/no questions, each asked twice (#647, #649).

The open checker (`storyforge.checker`) reads a scene and reports whatever
it finds; the gate takes the union of two such readings
(`checker.merge_readings`), which raises recall and multiplies false
alarms. The stage sheet's fallback (#647) and the gate's question layer
(#649, `storyforge.questions`) ask narrow questions instead, each one
twice, and keep only what every asking agrees on: the intersection of
narrow readings, not the union of open ones.

This is the machinery both share; each caller owns its prompt, its schema
and what an answer means:

- `structured_call`: one structured call, retried once on an unusable reply
  (cut off, or off the schema), raising the caller's error otherwise.
- `ask`: all of a scene's questions in one call per asking, `ASKINGS`
  askings. The caller's prompt builder gets the asking's number, so a later
  asking can list the questions in reverse and say which asking it is (its
  own request, and the order doesn't lean every answer the same way). A
  later asking logs beside the first (`asking_log`).
- `parse_answers`: n → the answer's fields, for questions 1..count, each
  answered exactly once.
- `agreed`: the questions every asking gave the same answer to, and how
  many got split answers (never a finding: the caller says so).
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable

#: How many times each question is asked; a finding needs every asking
ASKINGS = 2


def structured_call(prompt: str, model: str, log_file: str, tokens: int, schema: dict,
                    label: str, check: Callable[[str], object], what: str,
                    error: type[Exception]):
    """One structured call, retried once on an unusable reply (`check`
    raised ValueError, or the reply hit its token limit). Returns `check`'s
    value. Raises `error` on a refusal, an API failure, or a second bad
    reply, its message naming `what`."""
    from storyforge import api
    for attempt in (1, 2):
        try:
            if log_file:
                response = api.invoke_to_file(prompt, model, log_file, tokens,
                                              output_schema=schema, label=label)
            else:
                response = api.invoke(prompt, model, tokens, output_schema=schema, label=label)
            if api.is_truncated(response):
                raise ValueError('the reply hit its token limit')
            return check(api.extract_text(response))
        except ValueError as e:
            if attempt == 2:
                raise error(f'{what} failed twice: {e}') from e
            prompt = prompt + f'\n\nYour last answer was not usable: {e}. Answer in the schema.'
        except RuntimeError as e:   # RefusalError, an API failure
            raise error(f'{what} failed: {e}') from e
    raise AssertionError('unreachable')


def asking_log(log_file: str, asking: int) -> str:
    """Where asking `asking` logs: `log_file` for the first, `.a<n>` before
    its extension for a later one ('' when there is no log)."""
    if asking == 1 or not log_file:
        return log_file
    stem, ext = os.path.splitext(log_file)
    return f'{stem}.a{asking}{ext}'


def parse_answers(text: str, count: int, fields: tuple[str, ...] = ('why',)
                  ) -> dict[int, dict[str, str]]:
    """n → {'answer': 'yes'|'no', field: text, ...} for questions 1..count,
    each answered exactly once, every one of `fields` a string (stripped).
    Raises ValueError otherwise."""
    try:
        items = json.loads(text)['answers']
    except (TypeError, ValueError, KeyError) as e:
        raise ValueError(f'reply is not the schema ({e})') from e
    out: dict[int, dict[str, str]] = {}
    for it in items if isinstance(items, list) else []:
        # `type(...) is int`: JSON `true` is a bool, which isinstance takes as 1
        if not (isinstance(it, dict) and type(it.get('n')) is int
                and it.get('answer') in ('yes', 'no')
                and all(isinstance(it.get(f), str) for f in fields)):
            raise ValueError(f'an answer is not the schema: {it!r}'[:200])
        if it['n'] in out:
            raise ValueError(f'question {it["n"]} is answered twice')
        out[it['n']] = {'answer': it['answer'], **{f: it[f].strip() for f in fields}}
    missing = [n for n in range(1, count + 1) if n not in out]
    extra = [n for n in out if not 1 <= n <= count]
    if missing or extra:
        raise ValueError(f'answers must cover questions 1 to {count} exactly '
                         f'(missing {missing}, extra {extra})')
    return out


def ask(build_prompt: Callable[[int], str], count: int, *, model: str, log_file: str,
        tokens: int, schema: dict, label: str, what: str, error: type[Exception],
        fields: tuple[str, ...] = ('why',), askings: int = ASKINGS
        ) -> list[dict[int, dict[str, str]]]:
    """Ask `count` questions `askings` times, one call per asking
    (`build_prompt(asking)` makes its prompt). Returns each asking's answers
    (`parse_answers`), in asking order; [] when there are no questions.
    Raises `error` when an asking fails (`structured_call`)."""
    if not count:
        return []
    return [structured_call(build_prompt(n), model, asking_log(log_file, n), tokens, schema,
                            label, lambda t: parse_answers(t, count, fields), what, error)
            for n in range(1, askings + 1)]


def agreed(answers: list[dict[int, dict[str, str]]], count: int, answer: str
           ) -> tuple[list[int], int]:
    """The questions (1..count) every asking answered `answer`, and how many
    got that answer from some askings but not all (split: not a finding)."""
    every, split = [], 0
    for n in range(1, count + 1):
        said = [a[n]['answer'] for a in answers]
        if said and all(s == answer for s in said):
            every.append(n)
        elif answer in said:
            split += 1
    return every, split
