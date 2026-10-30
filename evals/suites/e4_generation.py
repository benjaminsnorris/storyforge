"""E4 generation: draft shared-dark Act 1 with today's write, judge it.
See ``evals/e4``."""

import os
from collections import Counter

import e4
from storyforge.gate import report_lines as gate_lines
from harness import Gate, Suite, SuiteOutput


def run(ctx):
    project = e4.project(ctx.work_dir)
    rows = e4.act_scenes(project)
    scene_ids = [r['id'] for r in rows]
    original = e4.clear_prose(project, scene_ids)
    gated = {}
    drafts, refused = e4.draft(project, scene_ids, gated=gated,
                               log_dir=os.path.join(ctx.work_dir, 'gate-logs'))
    judged = e4.judge(project, scene_ids, drafts)
    flags = e4.checker_flags(project, scene_ids)

    words = sum(len(t.split()) for t in drafts.values())
    target = sum(int(r['target_words']) for r in rows if r['id'] in drafts
                 and (r.get('target_words') or '').strip().isdigit())
    by_code: Counter = Counter()
    promises = 0
    notes = []
    for sid in scene_ids:
        if sid in refused:
            notes.append(f'{sid}: refused, not drafted — {refused[sid][:160]}')
            continue
        found = judged[sid]
        by_code.update(c['code'] for c in found['contradictions'])
        promises += len(found['broken_promises'])
        notes.append(f'{sid}: {len(drafts[sid].split())} words, '
                     f'{len(found["contradictions"])} contradiction(s), '
                     f'{len(found["broken_promises"])} broken promise(s)'
                     + ''.join(f'\n    {c["code"]}: {c.get("fact", "")[:160]}'
                               for c in found['contradictions'])
                     + ''.join(f'\n    PRM {p["field"]}: {p.get("why", "")[:160]}'
                               for p in found['broken_promises']))
    notes += [f'checker {f["scene_id"]}: {f["message"][:160]}' for f in flags]
    gate_failed = [s for s, g in gated.items() if not g.result.passed]
    gate_fixed = [s for s, g in gated.items() if g.fixed]
    notes.append(f'gate: {len(gated)} scene(s) gated, {len(gate_fixed)} fixed, '
                 f'{len(gate_failed)} still failing after the fix (write would stop at '
                 f'the first; E4 drafts on): {", ".join(gate_failed) or "none"}')
    for sid in gate_failed:
        notes += [f'  {sid}: {line[:200]}' for line in gate_lines(gated[sid].result)]
    notes.append('Judge stands in for the plan\'s human spot-check (still owed). '
                 'Drafted sequentially and gated, as write does by default; batch mode '
                 'is refused under a cassette.')
    contradictions = sum(by_code.values())
    code_counts = {code: {'contradictions': n} for code, n in by_code.items()}
    code_counts['PRM'] = {'broken_promises': promises}
    return SuiteOutput(
        metrics={
            'scenes': len(drafts),
            'refused': len(refused),
            'words': words,
            'target_words': target,
            'contradictions': contradictions,
            'cp10k': e4.per_10k(contradictions, words),
            'checker_flags': len(flags),
            'cp10k_checker': e4.per_10k(len(flags), words),
            'broken_promises': promises,
            'gate_fixed': len(gate_fixed),
            'gate_failed': len(gate_failed),
            'bps': round(promises / len(drafts), 3) if drafts else 0.0,
            'length_drift': e4.length_drift(rows, drafts),
            'voi': e4.mean_voice(list(drafts.values())),
            'voi_author': e4.mean_voice([original[s] for s in scene_ids
                                         if s in original and s in drafts]),
        },
        by_code=code_counts,
        gates=[Gate('scenes', len(drafts), '>=', len(scene_ids))],
        notes=notes,
    )


SUITE = Suite('e4-generation', 'Draft shared-dark Act 1 with write; CP10k, BPS, length, voice', run)
