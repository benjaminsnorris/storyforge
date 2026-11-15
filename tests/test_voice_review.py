"""The voice review (#655): one agent flags lines against checks.md, another
rewrites only those lines toward the voice."""

import json
import os

import pytest

from storyforge import voice_review as vr

PROSE = ('He opened his mouth. Nothing came out of it, which frightened him more than '
         'tears would have.\n\nShe did not let go. The fig tree, she said.\n')


def test_sentence_spans_cover_each_sentence():
    spans = vr.sentence_spans(PROSE)
    texts = [PROSE[a:b] for a, b in spans]
    assert texts[0] == 'He opened his mouth.'
    assert texts[1].startswith('Nothing came out') and texts[1].endswith('have.')
    assert texts[-1] == 'The fig tree, she said.'


def test_flag_spans_finds_the_sentence_even_with_curly_quotes_or_case():
    assert vr.flag_spans(PROSE, 'which frightened him') != []
    assert vr.flag_spans(PROSE, 'WHICH FRIGHTENED HIM') != []
    assert vr.flag_spans(PROSE, 'not in the scene') == []


def test_parse_review_drops_unverified_duplicate_and_over_cap_flags():
    flags = [{'quote': 'which frightened him', 'check': '1', 'why': 'explains'},
             {'quote': 'which frightened him', 'check': '1', 'why': 'again'},
             {'quote': 'a line nobody wrote', 'check': '2', 'why': 'x'}]
    flags += [{'quote': w, 'check': '3', 'why': 'x'} for w in
              ['He opened', 'his mouth', 'Nothing came', 'out of it', 'more than',
               'tears would', 'She did', 'not let go', 'The fig', 'tree, she',
               'she said', 'came out']]
    rev = vr.parse_review(json.dumps({'flags': flags}), PROSE)
    assert len(rev.flags) == vr.MAX_FLAGS and rev.over_cap == 1
    assert [f.quote for f in rev.unverified] == ['a line nobody wrote']


def _flags():
    return [vr.Flag('which frightened him more than tears would have', '1', 'explains'),
            vr.Flag('She did not let go', '2', 'fine')]


def test_an_edit_inside_its_sentence_is_applied_and_kept_flags_are_kept():
    reply = {'edits': [{'flag': 1, 'find': ', which frightened him more than tears would have',
                        'replace': ''}],
             'kept': [{'flag': 2, 'why': 'it lands'}]}
    rev = vr.apply_revision(PROSE, _flags(), reply)
    assert 'Nothing came out of it.' in rev.prose and rev.dropped == []
    assert rev.kept[0][1] == 'it lands' and rev.untouched == []


@pytest.mark.parametrize('edit, why', [
    ({'flag': 1, 'find': 'He opened his mouth.', 'replace': 'He gaped.'}, 'outside'),
    ({'flag': 3, 'find': 'He opened', 'replace': 'x'}, "which there isn't"),
    ({'flag': 1, 'find': 'not in the scene', 'replace': 'x'}, 'occur 0 times'),
])
def test_an_edit_outside_its_flag_is_refused(edit, why):
    rev = vr.apply_revision(PROSE, _flags(), {'edits': [edit], 'kept': []})
    assert rev.prose == PROSE and why in rev.dropped[0]
    assert rev.untouched == _flags()


def test_overlapping_edits_are_both_refused():
    flags = [vr.Flag('Nothing came out of it', '1', 'a'), vr.Flag('came out of it, which', '2', 'b')]
    reply = {'edits': [{'flag': 1, 'find': 'Nothing came out of it', 'replace': 'Silence'},
                       {'flag': 2, 'find': 'out of it, which', 'replace': 'x'}], 'kept': []}
    rev = vr.apply_revision(PROSE, flags, reply)
    assert rev.prose == PROSE and len(rev.dropped) == 2


def test_the_reviser_never_sees_the_checks_and_the_reviewer_does(project_dir, monkeypatch):
    from storyforge import api
    sent = []

    def fake(prompt, model, tokens, **k):
        sent.append(prompt)
        if 'flags' in k['output_schema']['properties']:
            return {'content': [{'type': 'text', 'text': json.dumps({'flags': [
                {'quote': 'He opened his mouth', 'check': '1', 'why': 'x'}]})}],
                'stop_reason': 'end_turn'}
        return {'content': [{'type': 'text', 'text': json.dumps({'edits': [], 'kept': [
            {'flag': 1, 'why': 'fine'}]})}], 'stop_reason': 'end_turn'}
    monkeypatch.setattr(api, 'invoke', fake)
    rev = vr.review(project_dir, 's', PROSE, model='m')
    vr.revise(project_dir, 's', PROSE, rev.flags, model='m')
    assert 'Her heart pounded' in sent[0]                  # checks.md, for the reviewer
    assert 'Her heart pounded' not in sent[1]              # never for the reviser
    assert 'The village was not there' in sent[1]          # the anchors are


def test_no_checks_no_review(project_dir):
    os.remove(os.path.join(project_dir, 'reference', 'voice', 'checks.md'))
    assert vr.review(project_dir, 's', PROSE, model='m').flags == []


def test_a_cut_off_review_is_an_error(project_dir, monkeypatch):
    from storyforge import api
    monkeypatch.setattr(api, 'invoke', lambda *a, **k: {
        'content': [{'type': 'text', 'text': '{"flags": ['}], 'stop_reason': 'max_tokens'})
    with pytest.raises(vr.VoiceReviewError, match='token limit'):
        vr.review(project_dir, 's', PROSE, model='m')


def test_the_record_says_what_happened(project_dir):
    flags = _flags()
    rev = vr.Review(flags=flags, unverified=[vr.Flag('gone', '3', 'x')])
    revision = vr.apply_revision(PROSE, flags, {
        'edits': [{'flag': 1, 'find': ', which frightened him more than tears would have',
                   'replace': ''}], 'kept': [{'flag': 2, 'why': 'it lands'}]})
    rel = vr.record(project_dir, 's', rev, revision)
    with open(os.path.join(project_dir, rel)) as f:
        text = f.read()
    assert '- after: (cut)' in text and 'Kept: it lands' in text and '"gone"' in text


def test_authors_marks_are_flags_for_the_reviser():
    flags = vr.flags_from_marks([('He opened his mouth.', 'more like this'), ('  ', 'x')])
    assert flags == [vr.Flag('He opened his mouth.', vr.AUTHOR, 'more like this')]
