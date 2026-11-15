"""Writing in the voice: the Austen reference voiceprint's test 6 (#654; plan
`docs/plans/2026-11-08-deterministic-gate-and-voiceprint.md`, B7 test 6).

One scene of an original book (`evals/fixtures/voice-austen/`: a card party
in a country town about 1810, none of her characters or events) is drafted
the way `storyforge write` drafts it: the book's `voice:` block names the
Austen reference voiceprint (`references/voiceprints/austen`), so the shared
system context carries her description and exemplars (all from *Pride and
Prejudice*), and the prompt is `cmd_write._build_prompt` with briefs. Then:

- **The meter** (free): the draft is measured and compared with Austen's
  fingerprint and with each of the seven other authors' (`vp.profile` of
  their ten chunks in `tests/fixtures/voiceprint/others/`, as test 1 does).
  `meter_rank` is Austen's place among the eight (1: nearest);
  `meter_margin` the nearest other author's distance minus hers (above 0:
  she is nearest). `austen_held_out_median` is the median distance of her
  own held-out chunks (*Emma*, *Persuasion*) from her fingerprint, for scale.
- **The judge** (paid): an Opus reader sees the draft and four unlabelled
  samples of about 500 words, from Austen (*Persuasion*, held out: not an
  exemplar), Brunton (*Self-Control*, 1811, her contemporary), Eliot
  (*Middlemarch*) and Dickens (*A Christmas Carol*), and names the one whose
  voice the draft is written in. It is asked four times with Austen's sample
  in each place in turn, so a preference for a position can't pass the test;
  `judge_austen` counts the times it named her.

The plan's target is the meter putting her nearest and the judge naming her.
The gates hold what was recorded (#488), with the target in the notes.

**Frozen** (#645): replayed, a miss is `stale`. Recorded only on purpose,
as three runs: `python3 evals/run.py --mode record --suite voice-austen
--runs 3` (each run drafts its own scene).

What this does not show: that the exemplars are what made the draft sound
like her. A period scene told to an Opus writer without the voice might come
close too; the comparison would need a book with no voice, which `write`
refuses to draft.
"""

import json
import os
import re
import shutil
import statistics

from harness import Gate, REPO_ROOT, Suite, SuiteOutput

FIXTURE = os.path.join(REPO_ROOT, 'evals', 'fixtures', 'voice-austen')
AUSTEN = os.path.join(REPO_ROOT, 'references', 'voiceprints', 'austen')
OTHERS_DIR = os.path.join(REPO_ROOT, 'tests', 'fixtures', 'voiceprint', 'others')
OTHERS = ('age-of-innocence', 'brimming-cup', 'christmas-carol', 'gatsby',
          'middlemarch', 'plastic-age', 'self-control')
SCENE = 'the-card-party'
DRAFT_MAX_TOKENS = 8192  # cmd_write's direct mode
#: the judge's four candidates: (name, where its sample comes from)
CANDIDATES = (
    ('Jane Austen', ('austen', 'persuasion')),
    ('Mary Brunton', ('others', 'self-control')),
    ('George Eliot', ('others', 'middlemarch')),
    ('Charles Dickens', ('others', 'christmas-carol')),
)
SAMPLE_WORDS = 500
LETTERS = 'ABCD'

#: what was recorded (run 1, 2026-11-15); the gates hold these (#488)
RECORDED_RANK = 1
RECORDED_JUDGE = 4

JUDGE_SCHEMA = {
    'type': 'object',
    'properties': {'pick': {'type': 'string', 'enum': list(LETTERS)},
                   'reason': {'type': 'string'}},
    'required': ['pick', 'reason'],
    'additionalProperties': False,
}


def _read(path):
    with open(path, encoding='utf-8') as f:
        return f.read()


def project(work_dir: str) -> str:
    """A working copy of the fixture book, its `voice:` block pointed at the
    Austen reference."""
    dest = os.path.join(work_dir, 'voice-austen')
    shutil.copytree(FIXTURE, dest)
    path = os.path.join(dest, 'storyforge.yaml')
    text = _read(path)
    if 'AUTHOR_REPO' not in text:
        raise RuntimeError(f'{path}: no AUTHOR_REPO placeholder in the voice: block')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text.replace('AUTHOR_REPO', AUSTEN))
    return dest


def draft(project_dir: str) -> str:
    """The scene, drafted as `write` drafts it (no gate: the voice is what's
    measured)."""
    from storyforge.api import extract_text, invoke
    from storyforge.cmd_write import _build_prompt
    from storyforge.common import build_shared_context, select_model
    from storyforge.parsing import clean_scene_content, extract_single_scene

    model = select_model('drafting')
    system = build_shared_context(project_dir, model=model)
    if not any('=== The Voice ===' in b.get('text', '') for b in system):
        raise RuntimeError('the shared context carries no voice: the voice: block was not read')
    prompt = _build_prompt(SCENE, project_dir, 'full', use_briefs=True, system_context=True)
    if not prompt:
        raise RuntimeError(f'could not build a drafting prompt for {SCENE}')
    text = extract_text(invoke(prompt, model, max_tokens=DRAFT_MAX_TOKENS,
                               label=f'voice-austen draft {SCENE}', system=system))
    prose = clean_scene_content(extract_single_scene(text) or text) if text else ''
    if len(prose.split()) < 1000:  # vp.MIN_COMPARE_WORDS: the meter needs it
        raise RuntimeError(f'the draft is {len(prose.split())} words; the meter needs 1000')
    return prose


def meter(prose: str) -> dict:
    """Each author's distance from the draft, nearest first, and the held-out
    Austen chunks' median distance from her fingerprint."""
    from storyforge import voiceprint as vp
    austen = vp.Fingerprint.load(os.path.join(AUSTEN, 'fingerprint.json'))
    candidates = {'austen': austen}
    for a in OTHERS:
        d = os.path.join(OTHERS_DIR, a)
        candidates[a] = vp.profile([vp.measure(_read(os.path.join(d, f)))
                                    for f in sorted(os.listdir(d))])
    values = vp.measure(prose)
    dist = {a: vp.compare_values(fp, values).distance for a, fp in candidates.items()}
    held = [vp.compare_values(austen, vp.measure(c)).distance
            for slug in ('emma', 'persuasion')
            for c in vp.chunks(_read(os.path.join(AUSTEN, 'corpus', f'{slug}.md')))]
    furthest = vp.compare_values(austen, values).furthest(5)
    return {'distances': dict(sorted(dist.items(), key=lambda kv: kv[1])),
            'held_out_median': statistics.median(held), 'furthest': furthest}


def sample(source: tuple[str, str]) -> str:
    """About SAMPLE_WORDS words of whole paragraphs from the middle of a
    candidate's text."""
    from storyforge import voiceprint as vp
    kind, slug = source
    if kind == 'austen':
        chunks = vp.chunks(_read(os.path.join(AUSTEN, 'corpus', f'{slug}.md')))
        text = chunks[len(chunks) // 2]
    else:
        text = _read(os.path.join(OTHERS_DIR, slug, '05.md'))
    paras = [p.strip() for p in re.split(r'\n\s*\n|\n', text)
             if p.strip() and not p.lstrip().startswith('#')]
    out, words = [], 0
    for p in paras[1:]:  # the first may start mid-paragraph
        out.append(p)
        words += len(p.split())
        if words >= SAMPLE_WORDS:
            break
    return '\n\n'.join(out)


def judge_prompt(prose: str, order: list[int], samples: list[str]) -> str:
    parts = ['Below is a passage of fiction, X, and samples of four authors\' writing, '
             'A to D. X was written in the voice of one of those four authors. The '
             'samples\' subjects and settings differ from X\'s and from each other\'s, '
             'so judge by the voice: how the sentences are built, the narrator\'s stance '
             'toward the characters and the reader, the irony, the diction. Name the '
             'sample whose author\'s voice X is written in, and say why in two or three '
             'sentences.', '', '## Passage X', '', prose.strip(), '']
    for letter, i in zip(LETTERS, order):
        parts += [f'## Sample {letter}', '', samples[i], '']
    return '\n'.join(parts)


def judge(prose: str) -> list[dict]:
    """The judge's pick with Austen's sample in each place in turn."""
    from storyforge.api import extract_text, invoke
    from storyforge.common import select_model
    model = select_model('checking')
    samples = [sample(src) for _, src in CANDIDATES]
    out = []
    for pos in range(len(LETTERS)):
        others = [i for i in range(1, len(CANDIDATES))]
        others = others[pos % len(others):] + others[:pos % len(others)]
        order = others[:pos] + [0] + others[pos:]
        reply = extract_text(invoke(judge_prompt(prose, order, samples), model, max_tokens=1024,
                                    label=f'voice-austen judge {pos + 1}',
                                    output_schema=JUDGE_SCHEMA))
        got = json.loads(reply)
        picked = CANDIDATES[order[LETTERS.index(got['pick'])]][0]
        out.append({'austen_at': LETTERS[pos], 'pick': got['pick'], 'author': picked,
                    'reason': got['reason']})
    return out


def run(ctx):
    proj = project(ctx.work_dir)
    prose = draft(proj)
    with open(os.path.join(proj, 'scenes', f'{SCENE}.md'), 'w', encoding='utf-8') as f:
        f.write(prose)
    m = meter(prose)
    dist = m['distances']
    ranked = list(dist)
    rank = ranked.index('austen') + 1
    nearest_other = min(v for a, v in dist.items() if a != 'austen')
    picks = judge(prose)
    named = sum(p['author'] == 'Jane Austen' for p in picks)
    notes = [f'draft: {len(prose.split())} words (target 2000)',
             'meter, nearest first: ' + ', '.join(f'{a} {v:.3f}' for a, v in dist.items()),
             f'held-out Austen chunks\' median distance from her: {m["held_out_median"]:.3f}',
             'furthest from her: ' + '; '.join(f'{d.name} {d.z:+.1f} sd' for d in m['furthest'])]
    notes += [f'judge, Austen at {p["austen_at"]}: named {p["author"]} ({p["pick"]}): '
              f'{p["reason"][:300]}' for p in picks]
    notes.append('Plan target (B7 test 6): meter_rank 1 and the judge naming Austen. The '
                 'gates hold what run 1 recorded (#488).')
    notes.append('Opening of the draft: ' + ' '.join(prose.split()[:80]))
    return SuiteOutput(
        metrics={'words': len(prose.split()),
                 'meter_rank': rank,
                 'meter_distance_austen': round(dist['austen'], 4),
                 'meter_margin': round(nearest_other - dist['austen'], 4),
                 'austen_held_out_median': round(m['held_out_median'], 4),
                 'judge_austen': named,
                 'judge_asked': len(picks)},
        gates=[Gate('meter_rank', rank, '<=', RECORDED_RANK),
               Gate('judge_austen', named, '>=', RECORDED_JUDGE)],
        notes=notes,
    )


SUITE = Suite('voice-austen', 'B7 test 6: a scene written with the Austen exemplars, on the '
              'meter and before a four-way judge', run, frozen=True)
