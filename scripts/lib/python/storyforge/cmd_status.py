"""storyforge status — deterministic next-step verdict.

Usage:
    storyforge status            # human-readable tree + recommended next step
    storyforge status --json     # structured verdict for tooling (e.g. forge)

Read-only, no LLM. Synthesizes the elaboration floor/coverage/consistency
checks plus phase and scene draft-state into one routable verdict.
"""

import argparse
import json

from storyforge.common import detect_project_root, get_medium
from storyforge.status import build_status

_STATE_MARK = {'solid': '✓', 'thin': '✗', 'not_started': '—'}


def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog='storyforge status',
        description='Deterministic next-step verdict for the current project.')
    parser.add_argument('--json', action='store_true', dest='json_output',
                        help='Emit the structured verdict as JSON')
    parser.add_argument('--dry-run', action='store_true',
                        help='No-op flag for interface parity (status never writes)')
    return parser.parse_args(argv)


def render_human(verdict: dict) -> str:
    lines = []
    match = ('matches storyforge.yaml' if verdict['phase_matches_yaml']
             else f"declared '{verdict['phase_declared']}'")
    suffix = '' if not verdict['phase_declared'] else f'  ({match})'
    lines.append(f"PHASE: {verdict['phase']}{suffix}")
    lines.append('LADDER:')
    for r in verdict['ladder']:
        mark = _STATE_MARK[r['state']]
        detail = f" — {r['detail']}" if r['detail'] else ''
        lines.append(f"  L{r['level']} {r['name']:<13} {mark} {r['state']}{detail}")
    nxt = verdict['next']
    cmd = f"  [{nxt['command']}]" if nxt['command'] else ''
    lines.append(f"NEXT:  {nxt['action']}{cmd}")
    if nxt['reason']:
        lines.append(f"       {nxt['reason']}")
    if verdict['then']:
        lines.append(f"THEN:  {verdict['then']['action']}")
    if verdict['blockers']:
        lines.append('BLOCKERS:')
        for b in verdict['blockers']:
            lines.append(f"  [{b['source']}] {b['detail']}")
    else:
        lines.append('BLOCKERS: none')
    return '\n'.join(lines)


def main(argv=None):
    args = parse_args(argv or [])
    project_dir = detect_project_root()
    medium = get_medium(project_dir) or 'novel'
    verdict = build_status(project_dir, medium)
    if args.json_output:
        print(json.dumps(verdict, indent=2))
    else:
        print(render_human(verdict))
