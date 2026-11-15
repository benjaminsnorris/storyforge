"""The voice-austen suite's free parts (#654, plan B7 test 6): the fixture
book, the judge's four orderings and samples, and the meter. The suite's
paid calls are frozen recordings (`evals/fixtures/cassettes/voice-austen`)."""

import os
import sys

from conftest import PLUGIN_DIR

sys.path.insert(0, str(PLUGIN_DIR / 'evals'))

from suites import voice_austen as va  # noqa: E402


def test_project_points_the_voice_block_at_the_austen_reference(tmp_path):
    from storyforge import voice_repo
    proj = va.project(str(tmp_path))
    ref = voice_repo.voice_ref(proj)
    assert ref is not None and os.path.samefile(ref.author_dir, va.AUSTEN)


def test_prompt_and_shared_context_carry_the_voice_and_the_brief(tmp_path):
    from storyforge.cmd_write import _build_prompt
    from storyforge.common import build_shared_context
    proj = va.project(str(tmp_path))
    system = build_shared_context(proj, model='claude-opus-5-5')
    assert any('=== The Voice ===' in b['text'] for b in system)
    prompt = _build_prompt(va.SCENE, proj, 'full', use_briefs=True, system_context=True)
    assert 'Six thousand, my dear' in prompt and '~2000 words' in prompt


def test_judge_puts_austen_in_each_place_once(monkeypatch):
    """Four asks, Austen's sample at A, B, C and D in turn, each ask showing
    all four samples; the pick is mapped back to the author shown there."""
    import storyforge.api as api
    prompts = []

    def fake_invoke(prompt, model, **kw):
        prompts.append(prompt)
        return {'content': [{'type': 'text', 'text': '{"pick": "B", "reason": "r"}'}]}

    monkeypatch.setattr(api, 'invoke', fake_invoke)
    monkeypatch.setenv('STORYFORGE_MODEL', 'claude-opus-5-5')
    samples = [va.sample(src) for _, src in va.CANDIDATES]
    picks = va.judge('Some prose.')
    assert [p['austen_at'] for p in picks] == list('ABCD')
    for p, prompt in zip(picks, prompts):
        heads = [prompt.index(f'## Sample {c}') for c in 'ABCD']
        shown = [next(i for i, s in enumerate(samples) if s in prompt[h:]
                      and prompt[h:].index(s) < 40) for h in heads]
        assert sorted(shown) == [0, 1, 2, 3]
        assert shown['ABCD'.index(p['austen_at'])] == 0
        assert p['author'] == va.CANDIDATES[shown[1]][0]
    assert sum(p['author'] == 'Jane Austen' for p in picks) == 1


def test_samples_are_whole_paragraphs_of_about_500_words():
    for _, src in va.CANDIDATES:
        words = len(va.sample(src).split())
        assert va.SAMPLE_WORDS <= words < 3 * va.SAMPLE_WORDS


def test_meter_puts_held_out_austen_nearest_her():
    from storyforge import voiceprint as vp
    with open(os.path.join(va.AUSTEN, 'corpus', 'persuasion.md'), encoding='utf-8') as f:
        chunk = vp.chunks(f.read())[3]
    m = va.meter(chunk)
    assert next(iter(m['distances'])) == 'austen'
    assert len(m['distances']) == 1 + len(va.OTHERS)
