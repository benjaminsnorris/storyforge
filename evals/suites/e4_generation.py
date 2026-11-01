"""E4 generation: draft shared-dark Act 1 with today's write, judge it.
See ``evals/e4``."""

import os
from collections import Counter

import e4
from storyforge.gate import report_lines as gate_lines
from harness import Gate, Suite, SuiteOutput


#: gate_measure's figures that mean nothing when no scene was gated
PARALLEL_DROPPED = ('gate_caught', 'gate_missed', 'gate_false_alarm', 'gate_catch_rate',
                    'scenes_passed', 'contradictions_passed', 'cp10k_passed',
                    'contradictions_in_failed', 'scenes_to_first_gate_failure')


def run(ctx):
    project = e4.project(ctx.work_dir)
    rows = e4.act_scenes(project)
    scene_ids = [r['id'] for r in rows]
    original = e4.clear_prose(project, scene_ids)
    parallel = e4.parallel()
    gated = {}
    drafts, refused = e4.draft(project, scene_ids, gated=None if parallel else gated,
                               log_dir=os.path.join(ctx.work_dir, 'gate-logs'))
    judged = e4.judge(project, scene_ids, drafts)
    flags = e4.checker_flags(project, scene_ids)

    target = sum(int(r['target_words']) for r in rows if r['id'] in drafts
                 and (r.get('target_words') or '').strip().isdigit())
    gate_failed = [s for s in scene_ids if s in gated and not gated[s].result.passed]
    measure = e4.gate_measure(scene_ids, drafts, judged, set(gate_failed))
    labels = measure['labels']
    by_code: Counter = Counter()
    notes = []
    headline = set(measure['headline'])
    for sid in scene_ids:
        if sid in refused:
            notes.append(f'{sid}: refused, not drafted — {refused[sid][:160]}')
            continue
        found = judged[sid]
        if sid in headline:
            by_code.update(c['code'] for c in found['contradictions'])
        notes.append(f'{sid}: {len(drafts[sid].split())} words, '
                     f'{len(found["contradictions"])} contradiction(s), '
                     f'{len(found["broken_promises"])} broken promise(s)'
                     + ('' if parallel else f', gate {labels[sid].replace("_", " ")}')
                     + ('' if sid in headline else ' (after write would have stopped)')
                     + ''.join(f'\n    {c["code"]}: {c.get("fact", "")[:160]}'
                               for c in found['contradictions'])
                     + ''.join(f'\n    PRM {p["field"]}: {p.get("why", "")[:160]}'
                               for p in found['broken_promises']))
    notes += [f'checker {f["scene_id"]}: {f["message"][:160]}' for f in flags]
    gate_fixed = [s for s, g in gated.items() if g.fixed]
    if not parallel:
        notes.append(f'gate: {len(gated)} scene(s) gated, {len(gate_fixed)} fixed, '
                     f'{len(gate_failed)} still failing after the fixes (write would stop at '
                     f'the first; E4 drafts on): {", ".join(gate_failed) or "none"}')
    for sid in gate_failed:
        notes += [f'  {sid}: {line[:200]}' for line in gate_lines(gated[sid].result)]
    notes.append('cp10k, contradictions, broken_promises, bps and words count the scenes '
                 'write would have drafted: up to the first refusal, or through the first '
                 'gate failure, inclusive (before this measure they counted every scene; '
                 'those figures are now *_all). scenes, length_drift and voi cover every '
                 'drafted scene. The *_all '
                 'figures count every drafted scene (the scenes after the first failure are '
                 'drafted from a ledger missing its facts). cp10k_passed is the rate in the '
                 'scenes the gate passed, anywhere in the act (what write would commit). '
                 'gate_caught / gate_missed / gate_false_alarm are per scene against the '
                 'judge\'s contradictions, over every drafted scene.')
    notes.append('The gate\'s checker and the judge are both Opus continuity reviews, so '
                 'part of a CP10k drop may be the two agreeing; the human spot-check is '
                 'still owed.')
    notes.append(f'Prior prose: {e4.prior_prose(project)}.')
    notes.append('Judge stands in for the plan\'s human spot-check (still owed). '
                 + ('Drafted as write --batch drafts (STORYFORGE_E4_PARALLEL=1): no earlier '
                    'prose and no gate, so no prompt depends on another scene\'s draft; the '
                    'Batch API itself is refused under a cassette. The gate figures (gate_*, *_passed, '
                    'contradictions_in_failed, scenes_to_first_gate_failure) are left out: '
                    'nothing was gated, so the headline counts stop only at a refusal.' if parallel else
                    'Drafted sequentially and gated, as write does by default; batch mode '
                    'is refused under a cassette.'))
    m = measure['metrics']
    if parallel:
        m = {k: v for k, v in m.items() if k not in PARALLEL_DROPPED}
    code_counts = {code: {'contradictions': n} for code, n in by_code.items()}
    code_counts['PRM'] = {'broken_promises': m['broken_promises']}
    return SuiteOutput(
        metrics={
            'scenes': len(drafts),
            'refused': len(refused),
            'target_words_all': target,
            'checker_flags': len(flags),
            'cp10k_checker_all': e4.per_10k(len(flags), m['words_all']),
            **({} if parallel else {'gate_fixed': len(gate_fixed),
                                    'gate_failed': len(gate_failed)}),
            'length_drift': e4.length_drift(rows, drafts),
            'voi': e4.mean_voice(list(drafts.values())),
            'voi_author': e4.mean_voice([original[s] for s in scene_ids
                                         if s in original and s in drafts]),
            **m,
        },
        by_code=code_counts,
        gates=[Gate('scenes', len(drafts), '>=', len(scene_ids))],
        notes=notes,
    )


SUITE = Suite('e4-generation', 'Draft shared-dark Act 1 with write; CP10k, BPS, length, voice', run)
