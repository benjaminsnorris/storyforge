"""Writing in the voice: the Austen reference voiceprint's test 6 (#654; plan
`docs/plans/2026-11-08-deterministic-gate-and-voiceprint.md`, B7 test 6).

One scene of an original book (`evals/fixtures/voice-austen/`: a card party
in a country town about 1810, none of her characters or events) is drafted
the way `storyforge write` drafts it in direct mode (its default; not
`--session`): the book's `voice:` block names the Austen reference
voiceprint (`references/voiceprints/austen`), so the shared system context
carries her description and exemplars (all from *Pride and Prejudice*), and
the prompt is `cmd_write._build_prompt` with briefs. The reply is held to
`write`'s checks (`api.stop_problem`, `parsing.unsafe_scene_reason`); unlike
`write`, no refusal fallback is sent (a cassette strips it) and the scene is
not gated. Then:

- **The meter** (free): the draft is measured and compared with Austen's
  fingerprint and with each of the seven other authors' (`vp.profile` of
  their ten chunks in `tests/fixtures/voiceprint/others/`, as test 1 does).
  `meter_rank` is Austen's place among the eight (1: nearest);
  `meter_margin` the nearest other author's distance minus hers (above 0:
  she is nearest). `austen_held_out_median` is the median distance of her
  own held-out chunks (*Emma*, *Persuasion*) from her fingerprint, for scale;
  a note says when the draft is further from her than any of them. Her
  fingerprint is the whole of *Pride and Prejudice*, each other author's ten
  chunks (a steadier center favours her a little; test 1 measures how much).
- **The judge** (paid): an Opus reader sees the draft and four unlabelled
  samples of about 500 words, from Austen (*Persuasion*, held out: not an
  exemplar), Brunton (*Self-Control*, 1811, her contemporary), Eliot
  (*Middlemarch*) and Dickens (*A Christmas Carol*), and names the one whose
  voice the draft is written in. Every name in the samples is replaced by an
  invented one (`neutral_names`), so the judge can't recognise a book by its
  people (#689 review SF-1: with the names left in, it cited "Mary and
  Charles Musgrove"). It is asked four times, the order turned one place
  each time (`orders`), so each sample sits in each place once and a
  preference for a position can't pass the test; `judge_austen` counts the
  times it named her. The setting still helps: only Austen's and Brunton's
  samples are of her period.

The plan's target is the meter putting her nearest and the judge naming her.
The gates hold what was recorded (#488), with the target in the notes.

**Frozen** (#645): replayed, a miss is `stale`. Recorded only on purpose,
as three runs: `python3 evals/run.py --mode record --suite voice-austen
--runs 3` (each run drafts its own scene).

What this does not show: that the exemplars are what made the draft sound
like her. A period scene told to an Opus writer without the voice might come
close too; the control would be a book with no voice, which `write` won't
draft, so it would measure a prompt `write` never sends.
"""

import glob
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
#: the judge's candidates: (name, where its sample comes from). Austen is
#: first (`AUSTEN_NAME`, index 0 in `orders`)
CANDIDATES = (
    ('Jane Austen', ('austen', 'persuasion')),
    ('Mary Brunton', ('others', 'self-control')),
    ('George Eliot', ('others', 'middlemarch')),
    ('Charles Dickens', ('others', 'christmas-carol')),
)
AUSTEN_NAME = CANDIDATES[0][0]
LETTERS = 'ABCDEFGH'[:len(CANDIDATES)]
SAMPLE_WORDS = 500
#: capitalised words `vp.proper_words` finds in the samples that are titles
#: or common nouns, not a person's or a place's name: kept
NOT_NAMES = frozenset({'mr', 'mrs', 'miss', 'lady', 'lord', 'sir', 'captain', 'master',
                       'rector', 'ghost', 'spirit', 'june', 'india'})
#: the invented names `neutral_names` gives, in order, one per name across
#: all the samples (none is a character of the four authors')
NEUTRAL = ('Ashby', 'Birtles', 'Colville', 'Darrow', 'Eskdale', 'Faulds', 'Gorringe',
           'Halsey', 'Ivers', 'Jarrow', 'Kestle', 'Lorimer', 'Mabey', 'Nettles', 'Orrin',
           'Pargeter', 'Quayle', 'Rendle', 'Stobart', 'Tennick', 'Usher', 'Vosper',
           'Warrick', 'Yelland', 'Abney', 'Cundy', 'Dimmock', 'Elphick', 'Hebden', 'Inchley',
           'Jowett', 'Kitto', 'Lumb', 'Mossop', 'Nunn', 'Oldroyd', 'Pinnock', 'Raikes',
           'Scorer', 'Tunnicliffe', 'Varley', 'Whitworth', 'Allott', 'Bratt', 'Crump',
           'Dobb', 'Eckersley', 'Fothergill', 'Grimshaw', 'Hirst', 'Illingworth', 'Jagger',
           'Kershaw', 'Lund', 'Marsden', 'Nuttall', 'Oddy', 'Pickles', 'Rhodes', 'Sowerby',
           'Thewlis', 'Uttley', 'Waddington', 'Yeadon')

#: what was recorded (run 1); the gates hold these (#488)
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


def check_voice(project_dir: str, system: list[dict]) -> list[str]:
    """The lines `write` logs for the book's voice, after checking the shared
    context carries all of Austen's: the author-voice preamble and every
    exemplar in the bank.

    Raises:
        RuntimeError: no `voice:` block, exemplar files the bank leaves out
            (`require_voice`'s WARNING), or the voice missing from the
            context, whole or in part.
    """
    from storyforge import voice_repo
    lines = voice_repo.require_voice(project_dir)
    if not lines:
        raise RuntimeError('the book has no voice: block: nothing of Austen\'s to write in')
    warnings = [ln for ln in lines if ln.startswith('WARNING')]
    if warnings:
        raise RuntimeError('; '.join(warnings))
    voice = '\n'.join(b.get('text', '') for b in system
                      if '=== The Voice ===' in b.get('text', ''))
    bank = voice_repo.book_voice(project_dir).exemplars.exemplars
    missing = [ex for ex in bank if ex.text.strip() not in voice]
    if voice_repo.VOICE_PREAMBLE not in voice or not bank or missing:
        raise RuntimeError('the shared context doesn\'t carry Austen\'s voice whole'
                           + (f': {len(missing)} of {len(bank)} exemplars missing'
                              if missing else ''))
    return lines


def draft(project_dir: str) -> tuple[str, list[str]]:
    """The scene, drafted as `write` drafts it in direct mode (no gate: the
    voice is what's measured), and notes on it (the voice read, the model).

    Raises:
        RuntimeError: the voice isn't carried whole (`check_voice`), the
            reply was refused or cut off, ends mid-sentence, or is too short
            for the meter.
    """
    from storyforge import voiceprint as vp
    from storyforge.api import extract_text, invoke, stop_problem
    from storyforge.cmd_write import _build_prompt
    from storyforge.common import build_shared_context, select_model
    from storyforge.parsing import clean_scene_content, extract_single_scene, unsafe_scene_reason

    model = select_model('drafting')
    system = build_shared_context(project_dir, model=model)
    notes = check_voice(project_dir, system)
    prompt = _build_prompt(SCENE, project_dir, 'full', use_briefs=True, system_context=True)
    if not prompt:
        raise RuntimeError(f'could not build a drafting prompt for {SCENE}')
    response = invoke(prompt, model, max_tokens=DRAFT_MAX_TOKENS,
                      label=f'voice-austen draft {SCENE}', system=system)
    problem = stop_problem(response)
    if problem:
        raise RuntimeError(f'the draft: {problem}')
    text = extract_text(response)
    scene = extract_single_scene(text) if text else None
    prose = clean_scene_content(scene or text) if text else ''
    problem = unsafe_scene_reason(prose)
    if problem:
        raise RuntimeError(f'the draft: {problem}')
    words = len(prose.split())
    if words < vp.MIN_COMPARE_WORDS:
        raise RuntimeError(f'the draft is {words} words; the meter needs {vp.MIN_COMPARE_WORDS}')
    notes.append(f'draft model: {response.get("model", model)}'
                 + ('' if scene else '; the reply had no scene markers, so all of it is '
                    'measured (as write saves it)'))
    return prose, notes


def meter(prose: str) -> dict:
    """Each author's distance from the draft, nearest first, and the held-out
    Austen chunks' median and largest distance from her fingerprint."""
    from storyforge import voiceprint as vp
    austen = vp.Fingerprint.load(os.path.join(AUSTEN, 'fingerprint.json'))
    candidates = {'austen': austen}
    for a in OTHERS:
        files = sorted(glob.glob(os.path.join(OTHERS_DIR, a, '*.md')))
        candidates[a] = vp.profile([vp.measure(_read(f)) for f in files])
    values = vp.measure(prose)
    dist = {a: vp.compare_values(fp, values).distance for a, fp in candidates.items()}
    held = [vp.compare_values(austen, vp.measure(c)).distance
            for slug in ('emma', 'persuasion')
            for c in vp.chunks(_read(os.path.join(AUSTEN, 'corpus', f'{slug}.md')))]
    furthest = vp.compare_values(austen, values).furthest(5)
    return {'distances': dict(sorted(dist.items(), key=lambda kv: kv[1])),
            'held_out_median': statistics.median(held), 'held_out_max': max(held),
            'furthest': furthest}


def neutral_names(texts: list[str]) -> list[str]:
    """`texts` with each name (`vp.proper_words` of each, less `NOT_NAMES`)
    replaced by an invented one from `NEUTRAL`: the same one wherever it
    occurs, and a different one for every name, so no two samples seem to
    share a person.

    Raises:
        RuntimeError: more names than `NEUTRAL` holds.
    """
    from storyforge import voiceprint as vp
    names = sorted({w[:-2] if w.endswith("'s") else w
                    for text in texts for w in vp.proper_words(text)} - NOT_NAMES)
    if len(names) > len(NEUTRAL):
        raise RuntimeError(f'{len(names)} names in the samples; NEUTRAL has {len(NEUTRAL)}')
    out = []
    for text in texts:
        for name, new in zip(names, NEUTRAL):
            text = re.sub(rf'\b{re.escape(name)}\b', new, text, flags=re.IGNORECASE)
        out.append(text)
    return out


def sample(source: tuple[str, str]) -> str:
    """At least SAMPLE_WORDS words of whole paragraphs from the middle of a
    candidate's text (names left in: `samples` replaces them).

    Raises:
        RuntimeError: an unknown source kind, or too few words of paragraphs.
    """
    from storyforge import voiceprint as vp
    kind, slug = source
    if kind == 'austen':
        chunks = vp.chunks(_read(os.path.join(AUSTEN, 'corpus', f'{slug}.md')))
        text = chunks[len(chunks) // 2]
    elif kind == 'others':
        text = _read(os.path.join(OTHERS_DIR, slug, '05.md'))
    else:
        raise RuntimeError(f'unknown sample source {kind!r}')
    paras = [p.strip() for p in re.split(r'\n\s*\n|\n', text)
             if p.strip() and not p.lstrip().startswith('#')]
    out, words = [], 0
    for p in paras[1:]:  # the first may start mid-paragraph
        out.append(p)
        words += len(p.split())
        if words >= SAMPLE_WORDS:
            break
    if words < SAMPLE_WORDS:
        raise RuntimeError(f'{slug}: {words} words of paragraphs; a sample needs {SAMPLE_WORDS}')
    return '\n\n'.join(out)


def samples() -> list[str]:
    """Every candidate's sample, in `CANDIDATES` order, names replaced."""
    return neutral_names([sample(src) for _, src in CANDIDATES])


def judge_prompt(prose: str, order: list[int], texts: list[str]) -> str:
    parts = ['Below is a passage of fiction, X, and samples of four authors\' writing, '
             'A to D. X was written in the voice of one of those four authors. The '
             'samples\' subjects and settings differ from X\'s and from each other\'s, '
             'so judge by the voice: how the sentences are built, the narrator\'s stance '
             'toward the characters and the reader, the irony, the diction. The names in '
             'the samples have been replaced. Name the sample whose author\'s voice X is '
             'written in, and say why in two or three sentences.', '', '## Passage X', '',
             prose.strip(), '']
    for letter, i in zip(LETTERS, order, strict=True):
        parts += [f'## Sample {letter}', '', texts[i], '']
    return '\n'.join(parts)


def orders() -> list[list[int]]:
    """Each ask's candidates by place: turned one place each time, so each
    candidate sits in each place once, and Austen (index 0) is at place
    `pos` in ask `pos`."""
    n = len(CANDIDATES)
    return [[(place - pos) % n for place in range(n)] for pos in range(n)]


def judge(prose: str) -> list[dict]:
    """The judge's pick in each of `orders()`.

    Raises:
        RuntimeError: an ask refused or cut off, or a reply that isn't the
            schema's JSON, named by its ask.
    """
    from storyforge.api import extract_text, invoke, stop_problem
    from storyforge.common import select_model
    model = select_model('checking')
    texts = samples()
    out = []
    for pos, order in enumerate(orders()):
        response = invoke(judge_prompt(prose, order, texts), model, max_tokens=1024,
                          label=f'voice-austen judge {pos + 1}', output_schema=JUDGE_SCHEMA)
        try:
            problem = stop_problem(response)
            if problem:
                raise ValueError(problem)
            got = json.loads(extract_text(response))
            place = LETTERS.index(got['pick'])
        except (ValueError, KeyError, TypeError) as e:
            raise RuntimeError(f'judge ask {pos + 1} (Austen at {LETTERS[pos]}): {e}') from e
        out.append({'austen_at': LETTERS[pos], 'pick': got['pick'],
                    'author': CANDIDATES[order[place]][0], 'reason': got.get('reason', ''),
                    'model': response.get('model', model)})
    return out


def run(ctx):
    proj = project(ctx.work_dir)
    prose, draft_notes = draft(proj)
    with open(os.path.join(proj, 'scenes', f'{SCENE}.md'), 'w', encoding='utf-8') as f:
        f.write(prose)
    m = meter(prose)
    dist = m['distances']
    rank = list(dist).index('austen') + 1
    nearest_other = min(v for a, v in dist.items() if a != 'austen')
    picks = judge(prose)
    named = sum(p['author'] == AUSTEN_NAME for p in picks)
    notes = draft_notes + [
        f'draft: {len(prose.split())} words (target 2000)',
        'meter, nearest first: ' + ', '.join(f'{a} {v:.3f}' for a, v in dist.items()),
        f'held-out Austen chunks\' distance from her: median {m["held_out_median"]:.3f}, '
        f'furthest {m["held_out_max"]:.3f}'
        + (' (the draft is further from her than any of her own chunks)'
           if dist['austen'] > m['held_out_max'] else ''),
        'furthest from her: ' + '; '.join(f'{d.name} {d.z:+.1f} sd' for d in m['furthest'])]
    notes += [f'judge ({p["model"]}), Austen at {p["austen_at"]}: named {p["author"]} '
              f'({p["pick"]}): {p["reason"][:300]}' for p in picks]
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
