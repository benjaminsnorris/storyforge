"""E8 revision safety: re-run current passes where past passes wrote errors.

See evals/e8/__init__.py. Gate (Phase 4, redefined 2026-11-01): at most
`MAX_UNFLAGGED` reintroduced errors reach the book unflagged: passed by the
gate, or written by a data pass, which isn't gated. The plan's "zero
reintroduced" is out of this checker's reach on one run: E8 moves between
runs (E6's three runs reintroduced 6, 10 and 11; 6 cases moved in or out
of reintroduced), and what was left after Phase 4's PRs was checker
recall (an inference miss, a long-context miss, a later scene not
searched), not an ungated path. A reintroduction in a scene the gate checked and failed is
listed for the author and revise stops there, so it doesn't count against
the gate (the listing is per scene: the gate may have failed it for another
finding); one the gate couldn't finish counts as unflagged, and
`gate_unfinished` must be zero. `reintroduced` is still reported.

`clean_gate_failed` counts the replays the judge found clean (the case's
error not reintroduced) that the gate didn't pass. They are not false
alarms by default: the judge looks only for the case's error, and most of
the first 14 (#478's recording) were other real errors the replay made
(2026-11-01). `gate_new` / `gate_plan_conflicts` / `gate_inherited` sum
what the gate's last run found over the gated replays (`e8.gate_counts`;
the naturalness-upstream family gates through revise itself and isn't
counted): `gate_inherited` is what was already in the scene before the
pass, reported but not blocking.
"""

import re

from e1 import load_cases, load_holdout
from e8 import (DATA_FAMILIES, PassHalted, family, judge, prepare, read_gate_counts, replay,
                select)
from harness import Gate, Suite, SuiteOutput

MIN_REPLAYED = 15  # below this the rate is too noisy to gate on
#: A judgement, set before the calendar re-record's result: E6's runs predate
#: the gate, so the spread of the unflagged count itself is unmeasured
MAX_UNFLAGGED = 2


def run(ctx):
    sel = select(load_cases(), load_holdout())
    notes = []
    by_code: dict[str, dict[str, float]] = {}
    by_family: dict[str, list[int]] = {}
    reintroduced = replayed = words = prose_hits = halted = unflagged = unfinished = 0
    clean_failed = 0
    found = {'new': 0, 'plan_conflicts': 0, 'extraction': 0, 'inherited': 0}
    for case in sel.cases:
        try:
            project, scene_id = prepare(case, ctx.work_dir)
        except LookupError as e:
            sel.exclude(f'unreplayable: {e}', case['id'])
            continue
        try:
            output = replay(case, project, scene_id)
        except PassHalted as e:
            halted += 1
            notes.append(f'{case["id"]} ({scene_id}): halted, nothing written — {str(e)[:160]}')
            continue
        data = family(case) in DATA_FAMILIES
        unjudged = data and not output.strip()
        if unjudged:  # a data pass that wrote nothing cannot have reintroduced anything
            verdict = {'verdict': 'not_present', 'evidence': ''}
        elif not output.strip():  # prose replays raise rather than return nothing
            raise RuntimeError(f'{case["id"]}: the replay returned no prose')
        else:
            verdict = judge(case, output)
        replayed += 1
        hit = verdict['verdict'] == 'reintroduced'
        reintroduced += hit
        # a gated prose pass that didn't pass leaves the scene listed for the
        # author (revise stops there); one it passed reaches the book unflagged
        listing = '' if data else _gate_listing(project, scene_id)
        flagged = listing == 'failed'
        unflagged += hit and not flagged
        unfinished += listing == 'unfinished'
        clean_failed += flagged and not hit
        counts = None if data else read_gate_counts(project)
        for k in found:
            found[k] += (counts or {}).get(k, 0)
        if not data:  # errors per 10k words counts prose only, on both sides
            words += len(output.split())
            prose_hits += hit
        code = by_code.setdefault(case['code'], {'replayed': 0, 'reintroduced': 0})
        code['replayed'] += 1
        code['reintroduced'] += hit
        fam = by_family.setdefault(family(case), [0, 0])
        fam[0] += 1
        fam[1] += hit
        notes.append(f'{case["id"]} ({scene_id}): {verdict["verdict"]}'
                     + (' (wrote nothing; not judged)' if unjudged else '')
                     + (' (the gate did not pass it: listed pending)' if flagged else '')
                     + (f' [gate: {_counts_note(counts)}]' if counts and any(counts.values())
                        else '')
                     + (' (the gate could not finish: counted unflagged)'
                        if listing == 'unfinished' else '')
                     + (f' — "{verdict.get("evidence", "")[:120]}"' if hit else ''))
    # after the loop, which adds the cases prepare() could not replay
    notes[:0] = [f'excluded {len(ids)}: {reason} ({", ".join(ids)})'
                 for reason, ids in sorted(sel.excluded.items())]
    unreplayable = sum(len(v) for k, v in sel.excluded.items() if k.startswith('unreplayable'))
    return SuiteOutput(
        metrics={'replayed': replayed, 'reintroduced': reintroduced,
                 'reintroduced_unflagged': unflagged, 'gate_unfinished': unfinished,
                 'clean_gate_failed': clean_failed,
                 **{f'gate_{k}': v for k, v in found.items()},
                 'reintroduction_rate': round(reintroduced / replayed, 3) if replayed else 0.0,
                 'errors_per_10k_words': round(prose_hits / words * 10000, 3) if words else 0.0,
                 'unreplayable': unreplayable, 'halted': halted,
                 **{f'family.{k}.replayed': v[0] for k, v in by_family.items()},
                 **{f'family.{k}.reintroduced': v[1] for k, v in by_family.items()}},
        by_code=by_code,
        gates=[Gate('replayed', replayed, '>=', MIN_REPLAYED),
               Gate('reintroduced_unflagged', unflagged, '<=', MAX_UNFLAGGED),
               # a gate that can't finish lists the scene too; it must not
               # pass for one that checked it
               Gate('gate_unfinished', unfinished, '==', 0)],
        notes=notes,
    )


def _counts_note(counts: dict[str, int]) -> str:
    names = {'new': 'new', 'plan_conflicts': 'plan conflict', 'extraction': 'extraction',
             'inherited': 'already in the scene'}
    return ', '.join(f'{v} {names[k]}' for k, v in counts.items() if v)


#: The reasons write/revise (and `e8.gate_as_revise`) list a scene with when
#: the gate ran and didn't pass it
_FAILED_REASON = re.compile(r'(the gate did not pass it|\d+ problem\(s\) after one fix)')
_UNFINISHED_REASON = re.compile(r'the gate (could not finish|failed unexpectedly)')


def _gate_listing(project_dir: str, scene_id: str) -> str:
    """How the replay left `scene_id` in working/gate-pending.csv:
    'failed' (the gate checked it and didn't pass it: write/revise stop
    there and the author is told), 'unfinished' (the gate couldn't finish),
    'other' (listed for another reason: a re-check, a pass's scene not gated
    yet), or '' (not listed: the gate passed it). Every gated family lists
    as write/revise do (`e8.gate_as_revise`, and naturalness-upstream through
    revise's own `_redraft_scenes`); the pre-pass projects predate the file.
    An unreadable file counts as not listed."""
    from storyforge import gate
    try:
        row = gate.pending(project_dir).get(scene_id)
    except gate.GateError:
        return ''
    if row is None:
        return ''
    if row['command'] in (gate.RECHECK, gate.RECHECK_FAILED):
        return 'other'
    reason = row['reason']
    if _UNFINISHED_REASON.match(reason):
        return 'unfinished'
    return 'failed' if _FAILED_REASON.match(reason) else 'other'


SUITE = Suite('e8-revision-safety',
              'Current revision passes vs the E1 errors past passes introduced', run)
