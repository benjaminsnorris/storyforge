"""`storyforge bibles convert` (#702) on a labelled set of synthetic essays.

The set is an invented book, *The Salt Ledger* (`fixtures/bibles-convert/`:
its registries and a character, world and systems bible essay, written for
this suite, no real book's prose), and `labels.json`: for each essay the
facts it settles (keyword groups a row's statement must hold, the subject
and type a correct row has, which are secrets and which are open
questions), its interpretation (traps a row must not carry), the lines it
quotes a character saying and its descriptions of speech (which are not
lines), and what resists rows (notes).

Each essay is converted as the command converts it (`bibles_convert.convert`,
one call at the command's default model) and scored:

- `fact_recall`: labelled facts some kept row states; `type_accuracy` and
  `subject_accuracy` over those found (a null subject isn't scored);
  `secrets_kept` (a secret as a knowledge row of category secret or
  reveal), `open_kept` (an open question as a row ending in `?`);
- `interpretation_rows` and `interpretation_notes`: kept rows, and notes,
  carrying the essay's interpretation (drafting reads bible-notes.md whole,
  so a note leaks as a row does); `speech_descriptions`: a description of
  how someone speaks kept as a fact or a note (#657: a voice is lines);
- `voice_recall`: quoted lines kept; `description_as_voice`: a description
  of speech kept as a line; `invented_lines`: lines the reply gave that the
  essay doesn't quote (left out by code: counted, never kept);
- `note_recall`: what resists rows, found in the notes;
- `rows`, `left_out`: counts, reported, not gated.

Gates hold each recorded value exactly (`FLOORS`, #488); the trust bar the
command is judged against is in the notes. Cheap and not frozen: a prompt
change is a re-record of three calls (about $0.07 on sonnet). With `FLOORS`
unset and no recordings, a replay is unavailable (`stale`, "not recorded
yet"), not an error.
"""

from __future__ import annotations

import json
import os
import shutil

from harness import EVALS_DIR, Gate, Suite, SuiteOutput, SuiteUnavailable, has_recordings

NAME = 'bibles-convert'
SET_DIR = os.path.join(EVALS_DIR, 'fixtures', 'bibles-convert')
LABELS = os.path.join(SET_DIR, 'labels.json')
BOOK = os.path.join(SET_DIR, 'book')

#: The recorded values, each held exactly (#488: a gain moves its floor in
#: the same commit; a loss is a decision). Recorded 2026-11-15 on sonnet 5.5
#: ($0.07 for the three essays; a first recording, before the prompt said
#: interpretation and descriptions of speech aren't notes or facts either,
#: put two interpretation notes and four speech descriptions in: $0.07)
FLOORS: dict[str, float | None] = {
    'fact_recall': 1.0, 'type_accuracy': 0.9796, 'subject_accuracy': 0.9655,
    'secrets_kept': 2, 'open_kept': 2, 'interpretation_rows': 0,
    'interpretation_notes': 0, 'speech_descriptions': 0,
    'voice_recall': 1.0, 'description_as_voice': 0, 'invented_lines': 0,
    'note_recall': 0.5,
}

#: What the command must reach before its rows are imported without a
#: read (the notes compare): not gated, since a gate no run passes says
#: nothing (#488)
TRUST_BAR = {'fact_recall': 0.9, 'type_accuracy': 0.9, 'interpretation_rows': 0,
             'interpretation_notes': 0, 'speech_descriptions': 0,
             'voice_recall': 1.0, 'description_as_voice': 0}


def load_labels(path: str = LABELS) -> dict:
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def _essay(book_dir: str, name: str) -> str:
    with open(os.path.join(book_dir, 'reference', name), encoding='utf-8') as f:
        return f.read()


def validate(labels: dict, book_dir: str = BOOK) -> list[str]:
    """Problems with the set; empty when sound: an essay that isn't there, a
    quoted line or a description of speech not in its essay, a fact label
    without keyword groups or with a type a row can't take, a subject no
    registry names, a repeated id."""
    from storyforge.bibles import IMPORT_TYPES
    from storyforge.bibles_convert import _normal
    from storyforge.elaborate import _read_csv
    ref = os.path.join(book_dir, 'reference')
    ids = {r['id'] for name in ('characters.csv', 'locations.csv')
           for r in _read_csv(os.path.join(ref, name))}
    problems, seen = [], set()
    for name, essay in labels['essays'].items():
        if not os.path.isfile(os.path.join(ref, name)):
            problems.append(f'{name}: no such essay in the set')
            continue
        text = _normal(_essay(book_dir, name)).lower()
        for item in essay['facts'] + essay['traps'] + essay['notes']:
            if item['id'] in seen:
                problems.append(f'{item["id"]}: id given twice')
            seen.add(item['id'])
        for f in essay['facts']:
            subject = f.get('subject')
            if 'subject' not in f or not (subject is None or isinstance(subject, str) or (
                    isinstance(subject, list) and subject
                    and all(isinstance(x, str) for x in subject))):
                problems.append(f'{f["id"]}: subject must be null (not scored), a string '
                                f'("" for none) or a non-empty list of strings')
            if not f.get('all'):
                problems.append(f'{f["id"]}: no keyword groups')
            if not set(f.get('types', [])) <= set(IMPORT_TYPES) or not f.get('types'):
                problems.append(f'{f["id"]}: types {f.get("types")} not all row types')
            for subject in _subjects(f) or []:
                if subject and subject not in ids:
                    problems.append(f'{f["id"]}: subject {subject!r} is in no registry')
        for v in essay['voices']:
            if v['character'] not in ids:
                problems.append(f'{name}: voice speaker {v["character"]!r} is in no registry')
            if _normal(v['line']).lower() not in text:
                problems.append(f'{name}: the line {v["line"][:40]!r} is not in the essay')
        for d in essay['not_voices']:
            if d.lower() not in text:
                problems.append(f'{name}: the description {d!r} is not in the essay')
    return problems


def _subjects(label: dict) -> list[str] | None:
    """A label's right subjects: None when it isn't scored, a list (either
    side of a relationship) or the one subject."""
    subject = label.get('subject')
    return None if subject is None else subject if isinstance(subject, list) else [subject]


def _has(statement: str, group: str) -> bool:
    return any(k in statement for k in group.split('|'))


def matches(label: dict, statement: str) -> bool:
    """Whether a row's statement states a labelled fact: every keyword group
    found (a group's alternatives `|`-separated), none of `without`."""
    s = statement.lower()
    return (all(_has(s, g) for g in label['all'])
            and not any(w in s for w in label.get('without', [])))


def score(labels: dict, conversions: dict) -> dict:
    """`conversions`: essay name → `bibles_convert.Conversion`. Returns
    metrics, and the missed, wrong and leaked ids for the notes."""
    from storyforge.bibles import REVEAL_CATEGORIES
    from storyforge.bibles_convert import NOT_QUOTED, _normal
    found = typed = placed = scored = secrets = secrets_kept = opens = opens_kept = 0
    total = leaks = note_leaks = lines = lines_kept = described = invented = 0
    speech = notes = notes_found = 0
    missed, wrong, leaked = [], [], []
    for name, essay in labels['essays'].items():
        conv = conversions[name]
        for label in essay['facts']:
            total += 1
            secrets += bool(label.get('secret'))
            opens += bool(label.get('open'))
            rows = [r for r in conv.facts if matches(label, r['statement'])]
            if not rows:
                missed.append(label['id'])
                continue
            found += 1
            subjects = _subjects(label)

            def right(row: dict) -> tuple[bool, bool]:
                return (row['type'] in label['types'],
                        subjects is None or row['subject'] in subjects)
            # the row that states it best: a fact several rows touch is
            # found right when one of them has its type and subject
            best = max(rows, key=right)
            ok_type, ok_subject = right(best)
            typed += ok_type
            if subjects is not None:
                scored += 1
                placed += ok_subject
            if not (ok_type and ok_subject):
                wrong.append(f'{label["id"]} ({best["type"]}, {best["subject"] or "-"})')
            if label.get('secret') and any(
                    r['type'] == 'knowledge' and r['category'].lower() in REVEAL_CATEGORIES
                    for r in rows):
                secrets_kept += 1
            if label.get('open') and any(r['statement'].rstrip().endswith('?') for r in rows):
                opens_kept += 1
        for trap in essay['traps']:
            hits = [r for r in conv.facts
                    if any(k in r['statement'].lower() for k in trap['any'])]
            in_notes = [n for n in conv.notes if any(k in n.lower() for k in trap['any'])]
            leaks += len(hits)
            note_leaks += len(in_notes)
            leaked += [trap['id']] * len(hits) + [f'{trap["id"]} (a note)'] * len(in_notes)
        speech += sum(any(d in text.lower() for d in essay['not_voices'])
                      for text in [r['statement'] for r in conv.facts] + conv.notes)
        kept = {(who, _normal(line)) for who, line in conv.voices}
        for v in essay['voices']:
            lines += 1
            lines_kept += (v['character'], _normal(v['line'])) in kept
        described += sum(any(d in line.lower() for d in essay['not_voices'])
                         for _, line in conv.voices)
        invented += sum(NOT_QUOTED in x for x in conv.left_out)
        for n in essay['notes']:
            notes += 1
            notes_found += any(any(k in note.lower() for k in n['any']) for note in conv.notes)
    r = lambda a, b: round(a / b, 4) if b else 0.0   # noqa: E731
    metrics = {
        'fact_recall': r(found, total), 'type_accuracy': r(typed, found),
        'subject_accuracy': r(placed, scored), 'secrets_kept': secrets_kept,
        'open_kept': opens_kept, 'interpretation_rows': leaks,
        'interpretation_notes': note_leaks, 'speech_descriptions': speech,
        'voice_recall': r(lines_kept, lines), 'description_as_voice': described,
        'invented_lines': invented, 'note_recall': r(notes_found, notes),
        'facts_labelled': total, 'secrets_labelled': secrets, 'open_labelled': opens,
        'rows': sum(len(c.facts) for c in conversions.values()),
        'left_out': sum(len(c.left_out) for c in conversions.values()),
    }
    return {'metrics': metrics, 'missed': missed, 'wrong': wrong, 'leaked': leaked}


def floor_gates(metrics: dict, floors: dict) -> tuple[list[Gate], list[str]]:
    gates, notes = [], []
    for name, floor in floors.items():
        value = metrics.get(name)
        gates.append(Gate(name, -1 if value is None else value, '==',
                          -1 if floor is None else floor))
        if floor is None:
            notes.append(f'{name} {value}: no floor recorded; set FLOORS[{name!r}] = {value}')
        elif value != floor:
            notes.append(f'{name} {value}, FLOORS {floor}: a change; moving the floor is a '
                         f'decision (see FLOORS)')
    return gates, notes


def trust_notes(metrics: dict) -> list[str]:
    """How the run compares with `TRUST_BAR`."""
    short = [f'{k} {metrics[k]} (bar {v})' for k, v in TRUST_BAR.items()
             if (metrics[k] < v if v else metrics[k] > v)]
    return ([f'below the trust bar, so convert writes rows for review: {", ".join(short)}']
            if short else ['at or past the trust bar on every measure'])


def run(ctx):
    from storyforge import bibles_convert as bc
    from storyforge.common import select_model
    if ctx.mode == 'replay' and all(v is None for v in FLOORS.values()) \
            and not has_recordings(ctx.cassette_dir):
        raise SuiteUnavailable(f'{NAME} is not recorded yet: '
                               f'python3 evals/run.py --mode auto --suite {NAME}')
    labels = load_labels()
    problems = validate(labels)
    if problems:
        raise ValueError(f'{NAME} fixtures: ' + '; '.join(problems))
    project = os.path.join(ctx.work_dir, 'book')
    shutil.copytree(BOOK, project)
    model = select_model(bc.MODEL_TASK)
    conversions = {name: bc.convert(project, name, model)[0] for name in labels['essays']}
    result = score(labels, conversions)
    m = result['metrics']
    gates, notes = floor_gates(m, FLOORS)
    notes += [f'model: {model}',
              f'missed ({len(result["missed"])} of {m["facts_labelled"]}): '
              + ', '.join(result['missed']),
              'found with the wrong type or subject: ' + (', '.join(result['wrong']) or 'none'),
              'interpretation kept as rows: ' + (', '.join(result['leaked']) or 'none'),
              *trust_notes(m)]
    return SuiteOutput(metrics=m, gates=gates, notes=notes)


SUITE = Suite(NAME, '`bibles convert` (#702) on synthetic essays with labelled facts, lines '
                    'and interpretation', run)
