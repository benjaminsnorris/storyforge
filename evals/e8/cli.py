#!/usr/bin/env python3
"""E8 planning, without API calls.

    python3 evals/e8/cli.py plan   # which cases replay, which scene, and an estimated recording cost
"""

from __future__ import annotations

import json
import os
import sys
import tempfile

EVALS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, EVALS_DIR)

import harness  # noqa: E402,F401  (puts the plugin library on sys.path)
import e1  # noqa: E402
import e8  # noqa: E402

JUDGE_OUTPUT_TOKENS = 200
REDRAFT_OUTPUT_TOKENS = 5000  # a typical scene; the cap is 16384


def main(argv=None) -> int:
    from storyforge.cmd_write import _build_prompt
    from storyforge.common import build_shared_context, model_for_tier, select_model
    from storyforge.costs import calculate_cost

    sel = e8.select(e1.load_cases(), e1.load_holdout())
    model = select_model('creative')
    total = 0.0
    data_cases = 0
    with tempfile.TemporaryDirectory(prefix='e8-plan-') as work:
        for case in sel.cases:
            try:
                project, scene_id = e8.prepare(case, work)
            except LookupError as e:
                sel.exclude(f'unreplayable: {e}', case['id'])
                continue
            if e8.family(case) in e8.DATA_FAMILIES:
                # a data pass's own calls depend on the project (hone batches,
                # one illustrate call over the whole book); only its judge is priced
                data_cases += 1
                usd = calculate_cost(model_for_tier('opus'), 4000, JUDGE_OUTPUT_TOKENS)
                total += usd
                print(f'{case["id"]:18} {case["code"]} {scene_id:32} data pass ({e8.family(case)}): '
                      f'judge ~${usd:.2f}, pass not priced')
                continue
            system = build_shared_context(project, model=model)
            prompt = _build_prompt(scene_id, project, 'full', use_briefs=True,
                                   system_context=bool(system), rewrite=True)
            in_tokens = (len(prompt) + len(json.dumps(system or []))) // 4
            usd = (calculate_cost(model, in_tokens, REDRAFT_OUTPUT_TOKENS)
                   + calculate_cost(model_for_tier('opus'), in_tokens // 8, JUDGE_OUTPUT_TOKENS))
            total += usd
            print(f'{case["id"]:18} {case["code"]} {scene_id:32} ~{in_tokens:>6} in  ~${usd:.2f}')
    for reason, ids in sorted(sel.excluded.items()):
        print(f'excluded {len(ids):>2}: {reason}  ({", ".join(ids[:6])}{" ..." if len(ids) > 6 else ""})')
    replay = len(sel.cases) - sum(len(v) for k, v in sel.excluded.items() if k.startswith('unreplayable'))
    print(f'{replay} case(s) to replay; estimated recording cost ~${total:.2f} '
          f'(model {model}; no prompt-cache discount assumed'
          + (f'; the own calls of {data_cases} data pass(es) are not included' if data_cases else '')
          + ')')
    return 0


if __name__ == '__main__':
    sys.exit(main())
