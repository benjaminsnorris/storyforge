"""E3 on the E1 corpus: does today's extraction capture the facts later scenes
contradicted? See ``evals/e3``."""

from collections import Counter

import e3
from harness import Gate, Suite, SuiteOutput

RECALL_GATE = 0.85


def run(ctx):
    items, excluded = e3.select()
    counts: Counter = Counter()
    by_code: dict[str, Counter] = {}
    notes = [f'excluded {len(ids)}: {reason}' for reason, ids in sorted(excluded.items())]
    for item in items:
        knowledge, physical, commitments = e3.extract(
            e3.project_for(item, ctx.work_dir), item['scene'])
        verdict = e3.judge(item, knowledge, physical, commitments)['verdict']
        counts[verdict] += 1
        by_code.setdefault(item['case']['code'], Counter())[verdict] += 1
        notes.append(f'{item["case"]["id"]} ({item["scene"]}): {verdict}')
    total = sum(counts.values())
    recall = round(counts['captured'] / total, 4) if total else 0.0
    return SuiteOutput(
        metrics={'facts': total, 'captured': counts['captured'], 'partial': counts['partial'],
                 'missing': counts['missing'], 'recall': recall,
                 'recall_with_partial': round((counts['captured'] + counts['partial']) / total, 4)
                 if total else 0.0},
        by_code={code: {'facts': sum(c.values()),
                        'recall': round(c['captured'] / sum(c.values()), 4)}
                 for code, c in by_code.items()},
        gates=[Gate('facts', total, '>=', 20), Gate('recall', recall, '>=', RECALL_GATE)],
        notes=notes,
    )


SUITE = Suite('e3-extraction', 'Today\'s extraction vs the facts E1 errors contradicted', run)
