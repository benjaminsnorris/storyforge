"""Finding a book's voice by blind sample rounds (#654; plan B5, and the
ready-to-draft plan's section 7, from *Wrath Like Smoke*'s rounds).

One scene is written several ways; the author marks sentences in a pull
request; the next round writes toward what was kept; the winner, ideally
finished by the author's hand, becomes an anchor (`reference/voice/anchors/`).
How the rounds worked on Wrath, and so how this runs:

- **One sentence per line** (`one_per_line`), so a comment attaches to a
  sentence. Paragraphs are kept with blank lines.
- **Unlabelled.** Samples are `Sample A`, `Sample B`... in a shuffled
  order; the key (what each tried) is kept outside the repo
  (`key_path`, under `~/.storyforge/voice-sample-keys/`), and given to the
  next round's writer, never to the author until the round is marked.
- **The rounds are PRs.** `storyforge voice sample` writes
  `working/voice-samples/round-<n>.md` on a branch, commits it and opens a
  PR. A later round (`--from-pr N`) reads every page of that PR's comments
  (`pr_marks`): line comments mapped to the sample and sentence they mark,
  `suggestion` blocks as the author's own wording, and general reactions.
- **Write toward the keeps**, not away from the cuts: round 3 obeyed every
  flagged problem and came out flat. The prompt says so.
- **Takes.** `--take <label>` revises one sample of the marked round
  toward its marks, in versions that differ in one named thing
  (`--versions "present tense;past tense"`, or two points of view).
- **Checked before it's shown.** Each sample gets the blocking read (one
  reading: physical slips) and, when the book has `checks.md`, the voice
  review; a separate reviser fixes only the flagged lines
  (`voice_review`). What was found and fixed is in the PR's description.
- **The winner** (`--promote <round file> --sample X --name N`) is saved
  as an anchor, with optional `kind:`, `tense:` and `pov:` headers, from
  the round file as it is now (the author's hand edits included).
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import re
from dataclasses import dataclass, field

from storyforge.common import log

SAMPLES_DIR = os.path.join('working', 'voice-samples')
KEYS_ROOT = os.path.join('~', '.storyforge', 'voice-sample-keys')
#: what a round varies when the author doesn't say
DEFAULT_VARY = ('narrator stance', 'distance', 'tense')
LABELS = 'ABCDEFGH'
#: the answer budget for a round: every variant in one reply
ROUND_TOKENS = 16000

VARIANTS_SCHEMA = {
    'type': 'object',
    'properties': {'variants': {'type': 'array', 'items': {
        'type': 'object',
        'properties': {'tried': {'type': 'string'}, 'text': {'type': 'string'}},
        'required': ['tried', 'text'],
        'additionalProperties': False,
    }}},
    'required': ['variants'],
    'additionalProperties': False,
}


class SampleError(RuntimeError):
    """A round can't be made: the message says why."""


# ============================================================================
# The round file
# ============================================================================

def one_per_line(text: str) -> str:
    """`text` with each sentence on its own line, paragraphs apart."""
    from storyforge.voice_review import sentence_spans
    paras = [p.strip() for p in re.split(r'\n\s*\n', text.strip()) if p.strip()]
    out = []
    for p in paras:
        flat = ' '.join(p.split())
        out.append('\n'.join(flat[a:b].strip() for a, b in sentence_spans(flat)))
    return '\n\n'.join(out)


def join_lines(text: str) -> str:
    """A sample's one-sentence-per-line text back into paragraphs."""
    paras = [p for p in re.split(r'\n\s*\n', text.strip()) if p.strip()]
    return '\n\n'.join(' '.join(line.strip() for line in p.split('\n') if line.strip())
                       for p in paras)


@dataclass
class Sample:
    label: str
    text: str                        # one sentence per line, as in the file
    lines: dict[int, str] = field(default_factory=dict)   # file line -> sentence


def parse_round(text: str) -> dict[str, Sample]:
    """The samples of a round file, by label, with each sentence's line
    number (1-based) in the file. A section is `## Sample X` or `## <name>`
    (a take's version); its word-count line is left out."""
    out: dict[str, Sample] = {}
    current: Sample | None = None
    body: list[str] = []
    for n, line in enumerate(text.split('\n'), start=1):
        m = re.match(r'^##\s+(?:Sample\s+)?(.+?)\s*$', line)
        if m:
            if current:
                current.text = '\n'.join(body).strip()
            current = Sample(m.group(1).strip(), '')
            out[current.label] = current
            body = []
            continue
        if current is None:
            continue
        if re.match(r'^\*\d[\d,]* words\*$', line.strip()):
            continue
        body.append(line)
        if line.strip():
            current.lines[n] = line.strip()
    if current:
        current.text = '\n'.join(body).strip()
    return out


def render_round(title: str, intro: str, samples: list[tuple[str, str]]) -> str:
    """A round file: the title, the intro, then each (label, text) sample,
    one sentence per line, with its word count."""
    parts = [f'# {title}', '', intro.strip(), '']
    for label, text in samples:
        flowing = one_per_line(text)
        words = len(flowing.split())
        heading = f'Sample {label}' if len(label) == 1 else label
        parts += [f'## {heading}', f'*{words:,} words*', '', flowing, '']
    return '\n'.join(parts).rstrip() + '\n'


INTRO = """{what}

Each sentence is on its own line, so you can comment on any sentence in the pull request: **keep**, **cut**, or **more like this** (and why, if it comes to you), or suggest your own wording. A general reaction to a whole sample is just as useful. {blind}"""


def next_round_number(project_dir: str) -> int:
    folder = os.path.join(project_dir, SAMPLES_DIR)
    taken = [int(m.group(1)) for n in (os.listdir(folder) if os.path.isdir(folder) else [])
             if (m := re.match(r'round-(\d+)\.md$', n))]
    return max(taken, default=0) + 1


def round_rel(n: int) -> str:
    return os.path.join(SAMPLES_DIR, f'round-{n}.md')


def key_path(project_dir: str, n: int) -> str:
    """Where round `n`'s key lives: outside the repo, so the author marks
    the samples blind."""
    real = os.path.realpath(project_dir)
    slug = f'{os.path.basename(real)}-{hashlib.sha1(real.encode()).hexdigest()[:8]}'
    return os.path.join(os.path.expanduser(KEYS_ROOT), slug, f'round-{n}.json')


def save_key(project_dir: str, n: int, key: dict) -> str:
    path = key_path(project_dir, n)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(key, f, indent=1, ensure_ascii=False)
    return path


def load_key(project_dir: str, n: int) -> dict:
    """Round `n`'s key ({} when it isn't on this machine)."""
    try:
        with open(key_path(project_dir, n), encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


# ============================================================================
# The marks on a round
# ============================================================================

@dataclass
class SampleMarks:
    """The author's marks on one sample: (sentence, note) on lines, the
    author's own wordings (suggestions), and whether a comment's line had
    moved since (outdated)."""
    marks: list[tuple[str, str]] = field(default_factory=list)
    suggestions: list[tuple[str, str]] = field(default_factory=list)
    outdated: int = 0


def marks_for_round(prs, round_text: str, round_path: str) -> tuple[dict[str, SampleMarks],
                                                                     list[str]]:
    """The PR's line comments on the round file, by sample, and notes on what
    couldn't be placed."""
    samples = parse_round(round_text)
    by_line = {n: (s.label, text) for s in samples.values() for n, text in s.lines.items()}
    out: dict[str, SampleMarks] = {label: SampleMarks() for label in samples}
    notes, unplaced = [], 0
    path = round_path.replace(os.sep, '/')
    for c in prs.lines:
        if c.path != path:
            continue
        where = by_line.get(c.line)
        if where is None:
            unplaced += 1
            continue
        label, sentence = where
        sm = out[label]
        if c.body:
            sm.marks.append((sentence, c.body))
        if c.suggestion:
            sm.suggestions.append((sentence, c.suggestion))
        sm.outdated += c.outdated
    if unplaced:
        notes.append(f'{unplaced} comment(s) on {path} are on lines that are no sample\'s '
                     f'sentence, left out')
    moved = sum(sm.outdated for sm in out.values())
    if moved:
        notes.append(f'{moved} comment(s) were on lines since changed; placed by their '
                     f'original line')
    return out, notes


def describe_marks(samples: dict[str, Sample], marks: dict[str, SampleMarks],
                   key: dict, general: list[str]) -> str:
    """The marked round, for the next round's writer: each sample, what it
    tried (the key), and the author's marks on it."""
    tried = key.get('tried', {})
    parts = ['## The last round, as the author marked it']
    for label, s in samples.items():
        parts.append(f'### Sample {label}'
                     + (f' (it tried: {tried[label]})' if label in tried else ''))
        parts.append(join_lines(s.text))
        sm = marks.get(label) or SampleMarks()
        if sm.marks:
            parts.append('Marks:\n' + '\n'.join(f'- "{q}": {n}' for q, n in sm.marks))
        if sm.suggestions:
            parts.append("The author's own wording:\n"
                         + '\n'.join(f'- "{q}" → "{w}"' for q, w in sm.suggestions))
        if not (sm.marks or sm.suggestions):
            parts.append('(not marked)')
    if general:
        parts.append('### The author\'s general reactions\n\n' + '\n\n'.join(general))
    return '\n\n'.join(parts)


# ============================================================================
# Writing a round
# ============================================================================

ROUND_PROMPT = """You are helping an author find the voice of their novel, {title}, by writing one scene several ways for them to react to, sentence by sentence.

{voice}

## The scene

{plan}

## This round

Write {n} versions of this scene, each {words} words. The events are the same in each; only the voice changes. Vary {vary} across them{influences}. Make each version a real attempt at a voice an author would want to keep, not a parody of a style.
{direction}
For each version, say in one line what it tried (`tried`): the narrator's stance, the distance, the tense, the blend. The author won't see these until the round is marked.

Write the scenes as a novel's prose: no title, no notes. Plain, concrete, no stock phrasing."""

DIRECTION = """
{marked}

Write toward what the author kept and asked for more of: those lines are the voice. A cut tells you what's wrong with one line, not what's right; a round that only avoids the cuts comes out flat. Use the author's own wordings where given. Where a general reaction names a direction, take it.
"""

TAKE_PROMPT = """You are helping an author find the voice of their novel, {title}. Below is a sample they marked, line by line. Revise it toward their marks: keep what they kept, take their own wordings, change what they asked to change, and write toward the lines they liked. The events stay the same.

{voice}

## The scene

{plan}

{marked}

Write {n} versions of the revised sample, which differ only in this: {versions}. Each version's `tried` is the one it is ({names})."""


@dataclass
class Round:
    """A round made: the round file's text, the key, and the notes on what
    the checks found and fixed."""
    number: int
    text: str
    key: dict
    notes: list[str] = field(default_factory=list)


def _voice_text(project_dir: str) -> str:
    from storyforge import voice_book
    voice = voice_book.resolve(project_dir)
    voice.raise_if_unreadable(project_dir)
    if voice.kind == 'ok':
        return voice.text
    return ('## The voice so far\n\nNone yet: this round is how it is found. Write each '
            'version in a distinct, deliberate voice.')


def _scene_context(project_dir: str, scene_id: str) -> str:
    from storyforge import session
    return session.scene_plan(project_dir, scene_id, notes=True)


def _ask_variants(prompt: str, model: str, log_file: str, project_dir: str,
                  scene_id: str) -> list[dict]:
    from storyforge.api import RefusalError, extract_text, invoke, is_truncated, log_reply
    try:
        response = invoke(prompt, model, ROUND_TOKENS, label=f'voice sample {scene_id}',
                          output_schema=VARIANTS_SCHEMA)
    except (RefusalError, RuntimeError) as e:
        raise SampleError(f'the round could not be written ({e})') from e
    log_reply(project_dir, response, 'voice-sample', scene_id, model)
    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    with open(log_file, 'w', encoding='utf-8') as f:
        json.dump(response, f)
    if is_truncated(response):
        raise SampleError(f'the round\'s reply hit its token limit ({log_file})')
    try:
        variants = json.loads(extract_text(response))['variants']
    except (ValueError, KeyError, TypeError) as e:
        raise SampleError(f'the round\'s reply could not be read ({e}; {log_file})') from e
    variants = [v for v in variants if (v.get('text') or '').strip()]
    if not variants:
        raise SampleError(f'the round\'s reply has no sample ({log_file})')
    return variants


def check_samples(project_dir: str, scene_id: str, texts: dict[str, str], *, model: str,
                  log_dir: str) -> tuple[dict[str, str], list[str]]:
    """Each sample's physical slips (the blocking read, one reading) and,
    with checks.md, the voice review; a reviser fixes only what they flag.
    Returns the texts after it and notes for the PR. A check that can't run
    is said, never skipped silently."""
    from storyforge import blocking, voice_book, voice_review
    from storyforge.common import ReferenceDocError
    has_checks = bool(voice_book.checks_text(project_dir))
    out, notes = {}, []
    if not has_checks:
        notes.append('No reference/voice/checks.md yet: only physical slips were checked.')
    for label, text in texts.items():
        flags: list = []
        try:
            read = blocking.check_blocking(project_dir, scene_id, prose=text, model=model,
                                           readings=1,
                                           log_file=os.path.join(log_dir, f'{label}-blocking.json'))
            flags += [voice_review.Flag(f.scene_quote, 'blocking', f.explanation)
                      for f in read.findings if f.scene_quote]
        except blocking.BlockingError as e:
            notes.append(f'Sample {label}: the physical check didn\'t finish ({e}).')
        if has_checks:
            try:
                rev = voice_review.review(project_dir, scene_id, text, model=model,
                                          log_file=os.path.join(log_dir, f'{label}-review.json'))
                flags += rev.flags
            except (voice_review.VoiceReviewError, ReferenceDocError) as e:
                notes.append(f'Sample {label}: the voice review didn\'t finish ({e}).')
        flags = [f for f in flags if voice_review.flag_spans(text, f.quote)]
        if not flags:
            out[label] = text
            continue
        try:
            revision = voice_review.revise(project_dir, scene_id, text, flags, model=model,
                                           log_file=os.path.join(log_dir, f'{label}-revise.json'))
            out[label] = revision.prose
            notes.append(f'Sample {label}: {len(flags)} line(s) flagged before you saw it '
                         f'(physical slips, checks.md); {revision.summary()}.')
        except (voice_review.VoiceReviewError, ReferenceDocError) as e:
            out[label] = text
            notes.append(f'Sample {label}: {len(flags)} line(s) flagged, not fixed: the '
                         f'reviser didn\'t finish ({e}).')
    return out, notes


def write_round(project_dir: str, scene_id: str, *, variants: int, vary: list[str],
                influences: str, model: str, log_dir: str, marked: str = '',
                previous: dict | None = None, words: str = '300 to 500',
                rng: random.Random | None = None) -> Round:
    """Round `next_round_number`: `variants` versions of `scene_id`, checked,
    shuffled and labelled A, B, C... `marked`: the last round as the author
    marked it (`describe_marks`), for a round after the first.

    Raises:
        SampleError: the scene isn't in the book, or the round can't be written.
    """
    from storyforge import session
    from storyforge.common import read_yaml_field
    if not 2 <= variants <= len(LABELS):
        raise SampleError(f'--variants takes 2 to {len(LABELS)}, not {variants}')
    try:
        plan = _scene_context(project_dir, scene_id)
    except session.SessionError as e:
        raise SampleError(str(e)) from e
    title = read_yaml_field('project.title', project_dir) or 'Untitled'
    n = next_round_number(project_dir)
    infl = f', blending these influences: {influences}' if influences else ''
    prompt = ROUND_PROMPT.format(title=title, voice=_voice_text(project_dir), plan=plan,
                                 n=variants, words=words, vary=', '.join(vary),
                                 influences=infl,
                                 direction=DIRECTION.format(marked=marked) if marked else '')
    got = _ask_variants(prompt, model, os.path.join(log_dir, f'round-{n}.json'), project_dir,
                        scene_id)
    rng = rng or random.Random()
    rng.shuffle(got)
    labelled = {LABELS[i]: v for i, v in enumerate(got[:len(LABELS)])}
    texts, notes = check_samples(project_dir, scene_id,
                                 {k: v['text'] for k, v in labelled.items()}, model=model,
                                 log_dir=os.path.join(log_dir, f'round-{n}-checks'))
    blind = ('They are shuffled and unlabelled; the key is shown after you mark them.')
    what = (f'{len(texts)} takes on the same slice of *{scene_id}*. The events are the same '
            f'in each; only the voice changes: {", ".join(vary)}'
            + (f', and how they blend {influences}' if influences else '') + '.')
    text = render_round(f'Voice samples, round {n}: {scene_id}',
                        INTRO.format(what=what, blind=blind),
                        list(texts.items()))
    key = {'round': n, 'scene': scene_id, 'vary': vary, 'influences': influences,
           'tried': {k: v['tried'] for k, v in labelled.items()},
           'from': previous or {}}
    return Round(n, text, key, notes)


def write_take(project_dir: str, scene_id: str, *, sample: str, marked: str,
               versions: list[str], model: str, log_dir: str) -> Round:
    """A take: one marked sample revised toward its marks, in versions that
    differ only in `versions` (one line each).

    Raises:
        SampleError: as `write_round`.
    """
    from storyforge import session
    from storyforge.common import read_yaml_field
    if len(versions) < 2:
        raise SampleError('--versions names at least two, separated by ";"')
    try:
        plan = _scene_context(project_dir, scene_id)
    except session.SessionError as e:
        raise SampleError(str(e)) from e
    title = read_yaml_field('project.title', project_dir) or 'Untitled'
    n = next_round_number(project_dir)
    prompt = TAKE_PROMPT.format(title=title, voice=_voice_text(project_dir), plan=plan,
                                marked=marked, n=len(versions),
                                versions=' / '.join(versions),
                                names='; '.join(versions))
    got = _ask_variants(prompt, model, os.path.join(log_dir, f'round-{n}.json'), project_dir,
                        scene_id)
    named = {}
    for i, v in enumerate(got[:len(versions)]):
        named[versions[i]] = v['text']
    texts, notes = check_samples(project_dir, scene_id, named, model=model,
                                 log_dir=os.path.join(log_dir, f'round-{n}-checks'))
    what = (f'Sample {sample} of the last round, revised toward your marks, in '
            f'{len(texts)} versions: ' + '; '.join(texts) + '.')
    text = render_round(f'Voice samples, round {n}: {scene_id}, take on sample {sample}',
                        INTRO.format(what=what, blind=''), list(texts.items()))
    key = {'round': n, 'scene': scene_id, 'take': sample, 'versions': versions,
           'tried': {k: k for k in texts}}
    return Round(n, text, key, notes)


# ============================================================================
# The winner
# ============================================================================

def promote(project_dir: str, round_file: str, label: str, name: str, *, kind: str = '',
            tense: str = '', pov: str = '', force: bool = False, dry_run: bool = False) -> str:
    """Save sample `label` of `round_file` (as it is now, hand edits
    included) as `reference/voice/anchors/<name>.md`. Returns its path.

    Raises:
        SampleError: no such sample, an anchor of that name (without
            `force`), a bad name or tense.
    """
    from storyforge import voice_book
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]*', name):
        raise SampleError(f'--name {name!r}: use lowercase letters, digits and hyphens')
    if tense and tense not in voice_book.TENSES:
        raise SampleError(f'--tense takes {" or ".join(voice_book.TENSES)}, not {tense!r}')
    path = round_file if os.path.isabs(round_file) else os.path.join(project_dir, round_file)
    try:
        with open(path, encoding='utf-8') as f:
            samples = parse_round(f.read())
    except OSError as e:
        raise SampleError(f'{round_file} can\'t be read ({e})') from e
    sample = samples.get(label)
    if sample is None:
        raise SampleError(f'{round_file} has no sample {label!r} (it has '
                          f'{", ".join(samples) or "none"})')
    rel = os.path.join(voice_book.ANCHORS_DIR, f'{name}.md')
    dest = os.path.join(project_dir, rel)
    if os.path.exists(dest) and not force:
        raise SampleError(f'{rel} is there already; pass --force to replace it')
    header = [f'{k}: {v}' for k, v in (('kind', kind), ('tense', tense), ('pov', pov)) if v]
    body = join_lines(sample.text)
    if dry_run:
        return rel
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, 'w', encoding='utf-8') as f:
        f.write(('\n'.join(header) + '\n\n' if header else '') + body + '\n')
    voice_book.parse_anchor(rel, open(dest, encoding='utf-8').read())   # it reads back
    return rel
