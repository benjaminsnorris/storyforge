"""The register check (#615): a source translation's archaic words, grammar
and idiom carried into a retelling's prose, runs of dialogue copied from the
source scene, the voice guide's exemptions, `score --register`, and the
re-voicing rule in the drafting, revision and voice prompts."""

import os

import pytest

from storyforge import register
from storyforge.register import Exemptions

from source_helpers import YAML, _write, import_source, make_adaptation

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _kinds(text, exemptions=Exemptions()):
    return [(f.kind, f.evidence) for f in register.pattern_findings('s', text, exemptions)]


# --- patterns: the shapes Weston's grammar left in A Year and a Day (G-036) ---

@pytest.mark.parametrize('text, evidence', [
    ('The lord bade Gawain take the other.', 'bade'),
    ('One marvel that befell in his days.', 'befell'),
    ('In the hall, a twelvemonth ago.', 'twelvemonth'),
    ('"I swear by my troth as a knight."', 'troth'),
    ('"I\'ll not be long."', "I'll not"),
    ('"I\'d not see that."', "I'd not"),
    ('"She\'ll not have expected you."', "She'll not"),
    ('"Bid me rise from this bench."', 'Bid me rise'),
    ('"I\'d sooner drop dead than fail of my errand."', 'fail of'),
    ('"Teach me something while my lord is from home."', 'lord is from home'),
    ('"And him that keeps it."', 'him that keeps'),
    ('Then said he, "Go."', 'Then said he'),
    ('"But that you\'re Gawain, I very much doubt."', "But that you're"),
    ('"There\'s no need of more."', 'no need of'),
    ('"See you remember it."', 'See you remember'),
    ('None of them would say it was he.', 'it was he'),
    ('He had half risen and stayed so, his hand out.', 'stayed so'),
    ('"It will be paid you promptly."', 'be paid you'),
    ('"No one bolder, nor better in the field."', 'nor better'),
    ('"Ask me no more."', 'Ask me no more'),
    ('"It isn\'t seemly."', 'seemly'),
    ('the finest spoil I\'ve seen these seven years', 'seen these seven years'),
    ('"I\'ve done ill," he said.', 'done ill'),
    ('"Yes, truly," he said.', 'Yes, truly'),
    ('"Hold yourself well paid."', 'Hold yourself well paid'),
    ('"May they have joy of it."', 'have joy of'),
])
def test_each_pattern_flags_its_shape(text, evidence):
    assert evidence in [e for _, e in _kinds(text)]


#: ordinary modern English that must give no findings (#615's review, R-2):
#: the reviewer's false positives, then more of the same shapes
MODERN = [
    'So now you know.',
    'I told him that was a bad idea.',
    "I see you don't like it.",
    'She went about her business.',
    'The house was in need of more work.',
    'She laughed for the sheer joy of it.',
    'Look what you have done.',
    'All the while, the rain kept on.',
    'You have to think on your feet.',
    'She laid it by the door.',
    'What is your asking price?',
    "He won't go, nor will she.",
    "I don't know what it was she wanted.",
    'She gave it her all.',
    'The girl that liked me moved away.',
    'He left, remarking that the sky was grey.',
    'Then came the rain.',
    'There stood a man in the doorway.',
    "She'd be all the better for it.",
    'These two years were the best of my life.',
    'I would like it well done.',
    'The letter is from home.',
    'No, I own it.',
    'Farewell, my friend.',
    'He had to go, whether he would or not.',
    'It was told over the intercom.',
    # more of the same shapes
    "I won't be long.",
    "I don't want to see that.",
    'Teach me something while my lord is away.',
    'It was he who did it.',
    'She stood so close he could smell the smoke.',
    'Neither better nor worse.',
    'He looked at the man who keeps the gate.',
    "You've spoiled it. That's a yes.",
    'He turned traitor in the end.',
    'She looked so tired.',
    'They bid him goodbye at the station.',
    'Whilst you were out, the phone rang.',
    'It all came to naught.',
    'The hoar frost lay on the grass.',
    'I paid it no mind.',
    'Give it time.',
    'He was tired these days.',
    'In these two years we built the house.',
    'She thought on the way home about the letter.',
    "I'll give it a try.",
    'It pleases me to say so.',
    'For the better part of a year he waited.',
    'They held it aside for her.',
    "She's in need of help.",
    'There was no need for that.',
    'Is he here?',
    'My asking him was a mistake.',
    "\u201cI\u2019m fine,\u201d she said.",
]


@pytest.mark.parametrize('text', MODERN)
def test_modern_sentences_are_not_flagged(text):
    assert _kinds(text) == []


def test_one_finding_per_pattern_per_sentence():
    found = register.pattern_findings('s', '"I\'ll not go, and I\'ll not stay."')
    assert [f.evidence for f in found] == ["I'll not"]
    assert found[0].sentence == '"I\'ll not go, and I\'ll not stay."'


def test_a_finding_names_its_scene_kind_and_sentence():
    [f] = register.pattern_findings('gawain-keeps-the-girdle', 'Calm now. He bade her go.')
    assert (f.scene_id, f.kind, f.evidence, f.sentence) == (
        'gawain-keeps-the-girdle', 'word', 'bade', 'He bade her go.')


# --- exemptions: declared in the voice guide ---

GUIDE = """# Voice Guide

## Style rules

- "by my faith" is not an exemption here: this section isn't the list.

## Register exemptions

- "by my faith", "God keep you" (oaths)
- "Dust thou art" (liturgy, quoted)
- scene: frame-teller, `frame-close`
* "Hark to her!" (a hunting cry)

### Notes

- "still inside the section"

## Banned words

- "not an exemption"
"""


def test_exemptions_read_phrases_and_scenes_under_their_heading():
    ex = register.read_exemptions(GUIDE)
    assert ex.phrases == ('by my faith', 'god keep you', 'dust thou art', 'hark to her!',
                          'still inside the section')
    assert ex.scenes == {'frame-teller', 'frame-close'}


def test_no_exemptions_heading_means_none():
    assert register.read_exemptions('# Voice Guide\n\n- "by my faith"\n') == Exemptions()


def test_an_exempt_phrase_skips_only_matches_inside_it():
    ex = register.read_exemptions(GUIDE)
    assert _kinds('"Dust thou art."', ex) == []
    # the oath is exempt, the old negative beside it is not
    assert _kinds('"By my faith, I\'ll not."', ex) == [('syntax', "I'll not")]
    assert _kinds('"Thou art late."', ex) == [('word', 'Thou art')]


def test_an_exempt_scene_has_no_findings():
    ex = register.read_exemptions(GUIDE)
    assert register.pattern_findings('frame-teller', 'It befell at Christmas.', ex) == []
    assert register.echo_findings('frame-teller', '"a b c d e"', {'x': 'a b c d e'}, ex) == []


def test_load_exemptions_reads_the_projects_voice_guide(tmp_path):
    assert register.load_exemptions(str(tmp_path)) == Exemptions()
    _write(tmp_path, {'reference/voice-guide.md': GUIDE})
    assert 'god keep you' in register.load_exemptions(str(tmp_path)).phrases


# --- source echo ---

WESTON = ('Then Gawain spake, "I beseech ye, my lord, let this venture be mine. Would ye '
          'but bid me rise from this seat, and stand by your side."')


def test_dialogue_sharing_a_run_with_the_source_is_an_echo():
    text = 'Gawain leaned in. "Bid me rise from this bench," he said.'
    [f] = register.echo_findings('s', text, {'gawain:takes': WESTON}, run=4, content=2)
    assert f.kind == 'echo' and f.evidence == 'Bid me rise from this'
    assert f.what == 'shares words with gawain:takes'
    assert f.sentence == 'Bid me rise from this bench,'


def test_echo_normalizes_the_translations_forms():
    """"I beseech ye" meets "I beseech you"; contractions meet their parts."""
    text = '"I beseech you, my lord, let this venture be mine."'
    [f] = register.echo_findings('s', text, {'src': WESTON})
    assert f.evidence == 'I beseech you, my lord, let this venture be mine'


def test_echo_reports_the_longest_run_once_a_sentence():
    text = '"Let this venture be mine, I beseech you, my lord, let this venture be mine."'
    found = register.echo_findings('s', text, {'src': WESTON})
    assert len(found) == 1
    assert found[0].evidence == 'I beseech you, my lord, let this venture be mine'


def test_runs_of_function_words_and_narration_are_not_echoes():
    src = 'and it was in the hall that he would be. The sun rose red over the wood.'
    # function words only; and narration (outside quotes) isn't checked
    assert register.echo_findings('s', '"And it was in the hall."', {'s': src}) == []
    assert register.echo_findings('s', 'The sun rose red over the wood.', {'s': src}) == []
    assert register.echo_findings('s', 'The sun rose red over the wood.', {'s': src},
                                  dialogue_only=False)


def test_an_echo_inside_an_exempt_phrase_is_skipped():
    src = 'He said, God keep you all, my good lords, and rode away.'
    ex = Exemptions(phrases=('god keep you all, my good lords',))
    assert register.echo_findings('s', '"God keep you all, my good lords."', {'s': src},
                                  ex, run=4, content=2) == []


def test_no_source_text_means_no_echo():
    assert register.echo_findings('s', '"Bid me rise from this seat."', {}) == []


# --- the project: source map, scenes, report ---

@pytest.fixture
def adapted(tmp_path):
    proj = make_adaptation(tmp_path)
    import_source(proj)
    _write(proj, {
        'reference/scenes.csv': ('id|seq|title|status\n'
                                 'athena-at-the-door|1|At the Door|drafted\n'
                                 'telemachus-sails-at-night|2|Night|drafted\n'),
        'reference/source-map.csv': (
            'scene_id|source_scenes|treatment|note\n'
            'athena-at-the-door|minerva-visits;assembly-called|compress|\n'
            'telemachus-sails-at-night||invent|\n'),
        'scenes/athena-at-the-door.md': (
            'Athena came to the door.\n\n"Then Pallas Minerva went down," she said, '
            '"and the son of Cronus sent two eagles."\n\nHe bade her sit.\n'),
        'scenes/telemachus-sails-at-night.md': 'They sailed all night.\n',
    })
    return proj


def test_source_texts_follow_the_source_map(adapted):
    found = register.source_texts_by_scene(adapted)
    texts = found.texts
    assert found.gaps == {}
    assert set(texts) == {'athena-at-the-door'}
    assert set(texts['athena-at-the-door']) == {'odyssey:minerva-visits',
                                                'odyssey:assembly-called'}


def test_no_source_block_means_no_source_texts(project_dir):
    assert register.source_texts_by_scene(project_dir) == register.SourceTexts()


def test_check_scenes_runs_both_checks(adapted):
    checked = register.check_scenes(['athena-at-the-door', 'telemachus-sails-at-night'],
                                    adapted)
    kinds = {(f.kind, f.evidence) for f in checked.findings}
    assert ('word', 'bade') in kinds
    assert any(k == 'echo' for k, _ in kinds)
    assert checked.echo_note == '' and checked.unchecked == {}


def test_check_scenes_names_missing_and_unreadable_scenes(adapted):
    with open(os.path.join(adapted, 'scenes', 'athena-at-the-door.md'), 'wb') as f:
        f.write(b'\xff\xfe')
    checked = register.check_scenes(['athena-at-the-door', 'nope'], adapted)
    assert checked.unchecked == {'nope': 'no scene file'}
    assert checked.unreadable == {'athena-at-the-door': 'UnicodeDecodeError'}


def test_without_a_source_the_echo_check_says_why(project_dir):
    checked = register.check_scenes(['act1-sc01'], project_dir)
    assert 'no source scenes to compare against' in checked.echo_note
    assert any('source echo not checked' in line for line in register.report_lines(checked))


def test_a_source_that_cant_be_read_is_said(adapted, monkeypatch):
    from storyforge import source

    def bad(project_dir):
        raise source.SourceError('broken map')
    monkeypatch.setattr(register, 'source_texts_by_scene', bad)
    checked = register.check_scenes(['athena-at-the-door'], adapted)
    assert checked.echo_note == "the source can't be read (broken map)"
    assert checked.findings   # the patterns still ran


def test_report_lines_are_one_line_each_and_pipe_free():
    checked = register.Checked(
        [register.Finding('s1', 'word', 'archaic word', 'bade', 'He bade | her\ngo.')], {}, '')
    assert checked.warnings() == []
    lines = register.report_lines(checked)
    assert lines[0] == 's1  word    "bade"  (archaic word)'
    assert '|' not in lines[1] and '\n' not in lines[1]
    assert lines[-1] == 'Register: 1 finding(s) in 1 scene(s) (word 1)'


# --- score --register ---

def _tree(root):
    return {os.path.join(d, n): os.path.getmtime(os.path.join(d, n))
            for d, _, files in os.walk(root) if '.git' not in d for n in files}


def test_score_register_prints_without_writing(adapted, monkeypatch, capsys):
    from storyforge import api, cmd_score
    monkeypatch.chdir(adapted)
    for name in ('invoke_to_file', 'invoke_api', 'submit_batch'):
        if hasattr(api, name):
            monkeypatch.setattr(api, name, lambda *a, **k: pytest.fail('no API call'))
    before = _tree(adapted)
    cmd_score.main(['--register'])
    out = capsys.readouterr().out
    assert 'athena-at-the-door  word    "bade"' in out
    assert 'Register: ' in out
    assert _tree(adapted) == before


def test_score_register_takes_scene_filters(adapted, monkeypatch, capsys):
    from storyforge import cmd_score
    monkeypatch.chdir(adapted)
    cmd_score.main(['--register', '--scenes', 'telemachus-sails-at-night'])
    out = capsys.readouterr().out
    assert 'athena-at-the-door' not in out
    assert 'Register: 0 finding(s) in 0 scene(s) (none)' in out


@pytest.mark.parametrize('flag', [['--readability'], ['--deterministic'], ['--direct'],
                                  ['--no-apply']])
def test_score_register_refuses_other_modes(adapted, monkeypatch, flag):
    from storyforge import cmd_score
    monkeypatch.chdir(adapted)
    with pytest.raises(SystemExit) as e:
        cmd_score.main(['--register'] + flag)
    assert e.value.code == 1


def test_score_register_stops_on_an_unreadable_scene(adapted, monkeypatch, capsys):
    from storyforge import cmd_score
    monkeypatch.chdir(adapted)
    with open(os.path.join(adapted, 'scenes', 'athena-at-the-door.md'), 'wb') as f:
        f.write(b'\xff\xfe')
    with pytest.raises(SystemExit) as e:
        cmd_score.main(['--register'])
    assert e.value.code == 1
    assert "athena-at-the-door not checked: can't be read" in capsys.readouterr().out


def test_score_register_is_an_error_for_a_graphic_novel(monkeypatch):
    from storyforge import cmd_score_gn
    with pytest.raises(SystemExit) as e:
        cmd_score_gn.main(['--register'])
    assert e.value.code == 1


# --- the prompts ---

def test_an_adaptations_drafting_prompt_carries_the_revoicing_rule(adapted):
    from storyforge.prompts_source import REVOICE_RULE, drafting_section
    assert REVOICE_RULE in drafting_section(adapted, 'athena-at-the-door')
    # an invented scene has no source lines to re-voice
    assert REVOICE_RULE not in drafting_section(adapted, 'telemachus-sails-at-night')


def test_revision_section_lists_the_rule_and_findings(adapted):
    from storyforge.prompts_source import REVOICE_RULE
    section = register.revision_section(adapted, ['athena-at-the-door'])
    assert section.startswith('## Register\n\n' + REVOICE_RULE)
    assert '- athena-at-the-door: "He bade her sit." (word: bade; archaic word)' in section


def test_revision_section_caps_its_findings(adapted, monkeypatch):
    monkeypatch.setattr(register, 'REVISION_MAX_FINDINGS', 1)
    section = register.revision_section(adapted, ['athena-at-the-door'])
    assert section.count('\n- athena-at-the-door:') == 1
    assert 'more of the same kinds' in section


def test_revision_section_is_empty_without_a_source(project_dir):
    assert register.revision_section(project_dir, ['act1-sc01']) == ''


def test_the_revision_prompt_carries_the_register_section(adapted):
    from storyforge.revision import build_revision_prompt
    p = build_revision_prompt('polish', 'Polish the prose', 'athena-at-the-door', adapted,
                              api_mode=True)
    assert '\n## Register\n' in p and 'He bade her sit.' in p


def test_a_revision_prompt_without_a_source_has_no_register_section(project_dir):
    from storyforge.revision import build_revision_prompt
    p = build_revision_prompt('polish', 'Polish the prose', 'act1-sc01', project_dir,
                              api_mode=True)
    assert '## Register' not in p


def test_an_adaptations_voice_prompt_asks_for_exemptions_not_kept_nouns(adapted):
    from storyforge.prompts_elaborate import build_voice_prompt
    p = build_voice_prompt(adapted, PLUGIN)
    assert '**Re-voicing the source**' in p and '## Register exemptions' in p
    assert "Don't write a list of period or medieval nouns to keep" in p


def test_a_voice_prompt_without_a_source_is_unchanged(project_dir):
    from storyforge.prompts_elaborate import build_voice_prompt
    p = build_voice_prompt(project_dir, PLUGIN)
    assert 'Re-voicing the source' not in p and 'Register exemptions' not in p


def test_the_voice_stage_asks_for_exemptions_the_check_reads(adapted):
    """The bullets the voice prompt shows as examples are ones read_exemptions
    reads, and the shipped template's section reads as no exemptions."""
    import re as _re
    from storyforge.prompts_elaborate import build_voice_prompt
    p = build_voice_prompt(adapted, PLUGIN)
    examples = _re.findall(r'\(`(- [^`]+)`\)', p) + _re.findall(r'or `(- scene: [^`]+)`', p)
    assert examples, 'the voice prompt shows no example bullets'
    guide = '## Register exemptions\n\n' + '\n'.join(
        e.replace('<scene-id>', 'frame-teller') for e in examples) + '\n'
    ex = register.read_exemptions(guide)
    assert ex.phrases == ('by my faith',) and ex.scenes == {'frame-teller'}
    assert ex.problems == ()
    with open(os.path.join(PLUGIN, 'templates', 'reference', 'voice-guide.md'),
              encoding='utf-8') as f:
        assert register.read_exemptions(f.read()) == Exemptions()


# --- #615's review ---

def test_curly_apostrophes_match_like_straight_ones():
    """R-1: typeset prose uses ’; the patterns and exemptions saw none."""
    assert _kinds('“I’ll not go.” “’Tis late.”') == [('syntax', 'I’ll not'),
                                                    ('word', '’Tis')]
    ex = register.read_exemptions('## Register exemptions\n\n- "God\'s wounds" (an oath)\n'
                                  '- “I’ll not” (his habit)\n')
    assert _kinds('“God’s wounds, I’ll not.”', ex) == []
    assert _kinds('“God\'s wounds, thou fool.”', ex) == [('word', 'thou')]


def test_a_directly_built_exemption_is_folded_and_lowercased():
    """R-4: Exemptions(phrases=('By my faith',)) matched nothing."""
    ex = Exemptions(phrases=('Dust Thou Art',))
    assert ex.phrases == ('dust thou art',)
    assert _kinds('"Dust thou art."', ex) == []


def test_a_scene_exemption_may_give_a_reason():
    """R-3: the docstring's own example never matched."""
    ex = register.read_exemptions(
        '## Register exemptions\n\n'
        "- scene: brutus-founds-britain-after-troy (the Teller's frame)\n"
        '- scenes: `frame-open` (his voice); frame-close (the last)\n')
    assert ex.scenes == {'brutus-founds-britain-after-troy', 'frame-open', 'frame-close'}
    assert ex.problems == ()


@pytest.mark.parametrize('bullet, why', [
    ('- by my faith (an oath)', 'no double-quoted phrase'),
    ("- 'by my faith' (an oath)", 'no double-quoted phrase'),
    ('- "Dust thou art. Unto dust shalt thou return." (liturgy)', 'spans a sentence break'),
    ('- scene: (the frame)', 'scene id is missing'),
])
def test_an_exemption_that_cant_be_used_is_a_problem(bullet, why):
    """R-4: these were silently ignored."""
    ex = register.read_exemptions(f'## Register exemptions\n\n{bullet}\n')
    assert len(ex.problems) == 1 and why in ex.problems[0]
    assert ex.phrases == ()


def test_exemption_problems_and_unknown_scenes_are_warnings(adapted):
    """R-4: in report_lines and the revision build."""
    _write(adapted, {'reference/voice-guide.md': (
        '## Register exemptions\n\n- by my faith\n- scene: no-such-scene\n'
        '- scene: athena-at-the-door\n')})
    checked = register.check_scenes(['athena-at-the-door'], adapted)
    warnings = checked.warnings()
    assert any('no double-quoted phrase' in w for w in warnings)
    assert any('`scene: no-such-scene` names a scene not in reference/scenes.csv' in w
               for w in warnings)
    assert not any('scene: athena-at-the-door` names' in w for w in warnings)
    assert all(line in register.report_lines(checked) for line in warnings)
    seen = []
    register.revision_section(adapted, ['athena-at-the-door'], warn=seen.append)
    assert seen == warnings


def test_a_voice_guide_that_cant_be_read_is_a_problem_not_a_traceback(tmp_path):
    """R-12: IsADirectoryError, PermissionError, UnicodeDecodeError escaped."""
    os.makedirs(tmp_path / 'reference' / 'voice-guide.md')
    ex = register.load_exemptions(str(tmp_path))
    assert ex.phrases == () and "can't be read" in ex.problems[0]
    os.rmdir(tmp_path / 'reference' / 'voice-guide.md')
    (tmp_path / 'reference' / 'voice-guide.md').write_bytes(b'\xff\xfe\x00')
    assert "can't be read" in register.load_exemptions(str(tmp_path)).problems[0]


def test_revision_section_logs_what_it_couldnt_check(adapted):
    """R-5: the echo note and unchecked scenes were dropped."""
    _write(adapted, {'reference/source-map.csv': (
        'scene_id|source_scenes|treatment|note\n'
        'athena-at-the-door|minerva-visitz|compress|\n')})
    seen = []
    register.revision_section(adapted, ['athena-at-the-door', 'gone'], warn=seen.append)
    assert any('athena-at-the-door: source scenes not compared: minerva-visitz' in w
               for w in seen)
    assert 'WARNING: gone not checked: no scene file' in seen


def test_revision_section_warns_to_the_log_by_default(adapted, capsys):
    register.revision_section(adapted, ['gone'])
    assert 'WARNING: gone not checked: no scene file' in capsys.readouterr().out


def test_the_revision_prompt_sends_register_warnings_to_stderr(adapted, capsys):
    from storyforge.revision import build_revision_prompt
    _write(adapted, {'reference/voice-guide.md': '## Register exemptions\n\n- oops\n'})
    build_revision_prompt('polish', 'Polish', 'athena-at-the-door', adapted, api_mode=True)
    err = capsys.readouterr().err
    assert 'register exemptions' in err and 'no double-quoted phrase' in err


def test_the_revision_prompt_cli_reports_a_bad_source_block(adapted, monkeypatch, capsys):
    """R-12: a SourceError from the register section was a traceback."""
    from storyforge import revision
    _write(adapted, {'storyforge.yaml': 'source:\n  mode: free\n'})
    monkeypatch.setattr('sys.argv', ['revision', 'build-prompt', 'polish', 'Polish',
                                     'athena-at-the-door', adapted, '--api-mode'])
    with pytest.raises(SystemExit) as e:
        revision.main()
    assert e.value.code == 1
    assert capsys.readouterr().err.startswith('ERROR:')


@pytest.mark.parametrize('cell, why', [
    ('minerva-visitz', 'minerva-visitz (not found in one imported source)'),
    ('gods-debate;nope', 'nope (not found'),
])
def test_unresolved_source_refs_are_reported_per_scene(adapted, cell, why):
    """R-6: a typo in the map silently turned the echo check off."""
    _write(adapted, {'reference/source-map.csv': (
        'scene_id|source_scenes|treatment|note\n'
        f'athena-at-the-door|{cell}|compress|\n')})
    checked = register.check_scenes(['athena-at-the-door'], adapted)
    assert why in checked.source_gaps['athena-at-the-door']
    assert any(why in w for w in register.report_lines(checked))


def test_a_source_scene_with_no_prose_is_reported(adapted, monkeypatch):
    from storyforge import source
    monkeypatch.setattr(source, 'source_prose', lambda *a: '')
    checked = register.check_scenes(['athena-at-the-door'], adapted)
    assert ('odyssey:minerva-visits (no source prose)'
            in checked.source_gaps['athena-at-the-door'])


def test_an_invented_scene_has_no_source_gap(adapted):
    checked = register.check_scenes(['telemachus-sails-at-night'], adapted)
    assert checked.source_gaps == {}


def test_echo_run_extends_backward_over_function_words():
    """R-7: a run whose first windows were function words lost its start."""
    src = 'and so it was that the green knight rode into the hall at noon'
    [f] = register.echo_findings('s', '"And so it was that the green knight rode in."',
                                 {'s': src}, run=5, content=2)
    assert f.evidence == 'And so it was that the green knight rode'


def test_a_source_read_error_is_caught_but_not_a_value_error(adapted, monkeypatch):
    """R-8: ValueError was caught as "can't be read"; a bug must surface."""
    def bug(project_dir):
        raise ValueError('a bug')
    monkeypatch.setattr(register, 'source_texts_by_scene', bug)
    with pytest.raises(ValueError):
        register.check_scenes(['athena-at-the-door'], adapted)

    def undecodable(project_dir):
        raise UnicodeDecodeError('utf-8', b'\xff', 0, 1, 'bad')
    monkeypatch.setattr(register, 'source_texts_by_scene', undecodable)
    assert "can't be read" in register.check_scenes(['athena-at-the-door'], adapted).echo_note


def test_every_pattern_has_a_known_kind():
    """R-13."""
    assert {k for k, _, _ in register.PATTERNS} <= {'word', 'syntax', 'idiom'}
    with pytest.raises(AssertionError):
        register._compile([('grammar', r'x', 'bad kind')])


#: a value for each exclusive flag that takes one
_FLAG_VALUES = {'level': ['0'], 'compare': ['x'], 'boundary': ['0->1'], 'scope': ['x'],
                'source_fidelity': ['prose'], 'principles': ['avoid_passive']}


@pytest.mark.parametrize('mode, tuple_name', [('--register', '_REGISTER_EXCLUSIVE'),
                                              ('--readability', '_READABILITY_EXCLUSIVE')])
def test_free_modes_refuse_every_exclusive_flag_before_anything_runs(
        adapted, monkeypatch, mode, tuple_name):
    """R-9: an elaboration flag or --source-fidelity was dispatched first and
    ran (paid) instead; every flag in the exclusive tuple is now an ERROR
    before any dispatch (--level 0 included)."""
    from storyforge import cmd_score

    def boom(*a, **k):
        raise AssertionError('dispatched past the clash check')
    for fn in ('_run_elaboration_scoring', '_run_source_fidelity_only',
               '_run_readability_only', '_run_register_only', '_run_complete_cycle'):
        monkeypatch.setattr(cmd_score, fn, boom)
    monkeypatch.chdir(adapted)
    for name in getattr(cmd_score, tuple_name):
        if name == 'complete_cycle':
            continue     # --complete-cycle is dispatched first and refuses both itself
        flag = ['--' + name.replace('_', '-')] + _FLAG_VALUES.get(name, [])
        with pytest.raises(SystemExit) as e:
            cmd_score.main([mode] + flag)
        assert e.value.code == 1, name


def test_complete_cycle_refuses_the_free_modes(adapted, monkeypatch):
    from storyforge import cmd_score
    monkeypatch.chdir(adapted)
    for mode in ('--register', '--readability'):
        with pytest.raises(SystemExit) as e:
            cmd_score.main(['--complete-cycle', mode])
        assert e.value.code == 1
