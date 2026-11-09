"""storyforge voice — the author voice repo (plan Part B).

Run in an author voice repo (plan B0: `voice.yaml`, `corpus/`,
`fingerprint.json`), not in a book. So far it proposes and accepts the
described voice and the exemplar bank (B3, B4; `storyforge.voiceprint_proposals`):

1. `voice propose` reads a sample of the fingerprinted corpus alongside the
   fingerprint and makes two model calls: the description's claims go to
   `proposals/description-claims.csv` (an empty `mark` column), the exemplar
   shortlist to `proposals/shortlist.csv` and `proposals/shortlist/<id>.md`
   (an empty `pick` column). Paid: the forecast is printed first and held
   to the cost threshold (`STORYFORGE_COST_THRESHOLD`).
2. The author marks each claim `yes` or `no` (rewording any they keep), and
   writes `yes` in `pick` for each passage to keep (trimming its file if
   they like).
   `voice judge` measures the shortlist against the fingerprint again
   (free; after the fingerprint changes).
3. `voice accept` writes `description.md` from the claims marked yes and
   copies the picked passages to `exemplars/`. Free.

Usage:
    storyforge voice propose                    # both proposals, in this directory
    storyforge voice propose --dir ../ben-voice --only description
    storyforge voice propose --dry-run          # the sample and the forecast; no call
    storyforge voice judge                      # the shortlist's typical range again (free)
    storyforge voice accept                     # description.md and exemplars/
    storyforge voice accept --only exemplars --auto-pick   # pick by the reference rule

`voice propose` won't replace a claims file with marks in it, or a shortlist
with picks, without `--force`. Nothing is committed: commit the repo after.
"""

import argparse
import os
import sys

from storyforge.common import install_signal_handlers, log


def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog='storyforge voice',
        description='The author voice repo: propose and accept the described voice and '
                    'the exemplar bank.')
    sub = parser.add_subparsers(dest='action', required=True)
    prop = sub.add_parser('propose', help='Propose the description\'s claims and the '
                                          'exemplar shortlist (two model calls)')
    prop.add_argument('--dir', default='.', help='The author voice repo (default: here)')
    prop.add_argument('--only', choices=['description', 'shortlist'],
                      help='Make one of the two proposals')
    prop.add_argument('--model', help='The model (default: common.select_model'
                                      '(voiceprint_proposals.MODEL_TASK))')
    prop.add_argument('--force', action='store_true',
                      help='Replace a claims file with marks or a shortlist with picks')
    prop.add_argument('--dry-run', action='store_true',
                      help='Print the sample and the forecast; make no call')
    judge = sub.add_parser('judge', help='Measure the shortlist against the current '
                                         'fingerprint again (free)')
    judge.add_argument('--dir', default='.', help='The author voice repo (default: here)')
    acc = sub.add_parser('accept', help='Write description.md and exemplars/ from the '
                                        'author\'s marks and picks')
    acc.add_argument('--dir', default='.', help='The author voice repo (default: here)')
    acc.add_argument('--only', choices=['description', 'exemplars'],
                     help='Accept one of the two')
    acc.add_argument('--auto-pick', action='store_true',
                     help='Pick the exemplars by the reference voiceprint\'s rule '
                          '(voiceprint_proposals.auto_picks), replacing the pick column')
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv if argv is not None else sys.argv[1:])
    install_signal_handlers()
    from storyforge import voiceprint_proposals as vpp
    voice_dir = os.path.abspath(args.dir)
    try:
        vpp.check_voice_dir(voice_dir)
        if args.action == 'propose':
            return _propose(voice_dir, args)
        if args.action == 'judge':
            passages = vpp.rejudge(voice_dir)
            typical = sum(1 for p in passages if p.typical)
            log(f'{vpp.SHORTLIST_FILE}: {typical} of {len(passages)} passages inside the '
                f'fingerprint\'s typical range')
            return 0
        return _accept(voice_dir, args)
    except vpp.ProposalError as e:
        log(f'ERROR: {e}')
        return 1


def _has_author_work(voice_dir: str, what: str) -> bool:
    """Whether the claims file has a mark, or the shortlist a pick, that a
    new proposal would throw away."""
    from storyforge import voiceprint_proposals as vpp
    if what == 'description':
        if not os.path.isfile(os.path.join(voice_dir, vpp.CLAIMS_FILE)):
            return False
        return any(c.mark for c in vpp.read_claims(voice_dir))
    if not os.path.isfile(os.path.join(voice_dir, vpp.SHORTLIST_FILE)):
        return False
    return any(p.pick for p in vpp.read_shortlist(voice_dir))


def _propose(voice_dir: str, args) -> int:
    from storyforge import api, costs
    from storyforge import voiceprint_proposals as vpp
    from storyforge.common import select_model
    costs.exit_if_bad_threshold()
    calls = [args.only] if args.only else ['description', 'shortlist']
    if not args.force:
        kept = [c for c in calls if _has_author_work(voice_dir, c)]
        if kept:
            files = [vpp.CLAIMS_FILE if c == 'description' else vpp.SHORTLIST_FILE
                     for c in kept]
            log(f'ERROR: {", ".join(files)} already holds the author\'s marks or picks; '
                f'a new proposal would replace them. Accept them first, or pass --force.')
            return 1
    voice = vpp.load_voice(voice_dir)
    sample = vpp.build_sample(voice.texts)
    system = vpp.system_blocks(voice, sample)
    model = args.model or select_model(vpp.MODEL_TASK)
    estimate = vpp.forecast(system, model, calls)
    log(f'Sample: {sample.windows} passages, {len(sample.paragraphs)} paragraphs, '
        f'{sample.words:,} words of {sum(p.get("words", 0) for p in voice.fingerprint.pieces):,} '
        f'fingerprinted')
    log(f'Forecast: ${estimate:.2f} on {model} ({", ".join(calls)})')
    if args.dry_run:
        log('Dry run: no call made.')
        return 0
    if not costs.check_threshold(estimate):
        log(f'ERROR: the forecast ${estimate:.2f} is over the cost threshold '
            f'(${costs.cost_threshold():g}; STORYFORGE_COST_THRESHOLD). Nothing run.')
        return 1

    status = 0
    replies = os.path.join(voice_dir, vpp.REPLIES_DIR)
    with api.metered() as meter:
        if 'description' in calls:
            claims, problems = vpp.propose_description(
                system, model, os.path.join(replies, 'description.json'))
            path = vpp.write_claims(voice_dir, claims)
            log(f'{len(claims)} claims -> {os.path.relpath(path, voice_dir)}: mark each '
                f'yes or no in the `mark` column')
            for p in problems:
                log(f'WARNING: {p}')
        if 'shortlist' in calls:
            passages, refused = vpp.propose_shortlist(
                system, sample, model, os.path.join(replies, 'shortlist.json'))
            rng = vpp.passage_range(voice.fingerprint, voice.texts)
            passages = [rng.judge(p) for p in passages]
            path = vpp.write_shortlist(voice_dir, passages)
            typical = sum(1 for p in passages if p.typical)
            log(f'{len(passages)} passages ({typical} inside the fingerprint\'s typical '
                f'range) -> {os.path.relpath(path, voice_dir)}: write yes in `pick` for '
                f'each to keep')
            for r in refused:
                log(f'WARNING: refused {r}')
            if len(passages) < vpp.SHORTLIST_MIN:
                log(f'ERROR: only {len(passages)} usable passages; the shortlist should '
                    f'hold {vpp.SHORTLIST_MIN} to {vpp.SHORTLIST_MAX}. Run it again '
                    f'(--only shortlist), or add passages by hand.')
                status = 1
    log(f'Spent ${meter.cost():.2f}')
    return status


def _accept(voice_dir: str, args) -> int:
    from storyforge import voiceprint_proposals as vpp
    status = 0
    if args.only != 'exemplars':
        try:
            done = vpp.accept_description(voice_dir)
            log(f'{vpp.DESCRIPTION_FILE}: {done.kept} of {done.total} claims kept')
        except vpp.ProposalError as e:
            log(f'ERROR: {e}')
            status = 1
    if args.only != 'description':
        try:
            if args.auto_pick:
                ids = vpp.auto_picks(vpp.read_shortlist(voice_dir))
                vpp.set_picks(voice_dir, ids)
                log(f'Picked {len(ids)} passages by the reference rule (auto_picks)')
            done = vpp.accept_exemplars(voice_dir)
            log(f'{vpp.EXEMPLARS_DIR}/: {done.kept} of {done.total} shortlisted passages')
            for note in done.notes:
                log(note)
        except vpp.ProposalError as e:
            log(f'ERROR: {e}')
            status = 1
    return status
