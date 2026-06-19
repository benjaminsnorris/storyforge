"""Tests for page_aspect + panel-differentiation heuristics in pages.py
(issue #263)."""

import os


def _write(tmp_path, body, fm_extra=''):
    path = tmp_path / 's01-p1.md'
    path.write_text(
        "---\npage_id: s01-p1\nscene_id: s01\npage_within_scene: 1\n"
        "total_pages_in_scene: 1\npanel_count: 6\n" + fm_extra + "---\n\n" + body
    )
    return str(path)


def _kinds(path):
    from storyforge.pages import validate_page_file
    return {f['kind'] for f in validate_page_file(path)}


# --- page_aspect parsing + default ------------------------------------------

def test_page_aspect_of_default_portrait():
    from storyforge.pages import page_aspect_of
    assert page_aspect_of({}) == 'portrait'
    assert page_aspect_of({'page_aspect': 'LANDSCAPE'}) == 'landscape'


def test_page_aspect_parses_as_scalar(tmp_path):
    from storyforge.pages import parse_page_file
    path = _write(tmp_path, 'body\n', 'page_aspect: landscape\n')
    assert parse_page_file(path)['page_aspect'] == 'landscape'


# --- inline-comment stripping (#263 parser fix) -----------------------------

def test_inline_comment_stripped_from_scalar(tmp_path):
    from storyforge.pages import parse_page_file
    path = _write(tmp_path, 'body\n',
                  'page_aspect: landscape  # double-page spread\n'
                  'target_model: gpt-image-2  # ChatGPT Images 2.0\n')
    page = parse_page_file(path)
    assert page['page_aspect'] == 'landscape'
    assert page['target_model'] == 'gpt-image-2'
    commented = page['extra']['_commented_fields'].split(';')
    assert 'page_aspect' in commented and 'target_model' in commented


def test_inline_comment_on_integer_field(tmp_path):
    """The lived-in format `prompt_iteration: 7  # note` must coerce to int."""
    from storyforge.pages import parse_page_file
    path = _write(tmp_path, 'body\n', 'prompt_iteration: 7  # whole-page approach\n')
    page = parse_page_file(path)
    assert page['prompt_iteration'] == 7
    assert '_bad_integer_fields' not in page['extra']


def test_hash_without_leading_space_not_treated_as_comment(tmp_path):
    from storyforge.pages import parse_page_file
    path = _write(tmp_path, 'body\n', 'scene_title: Issue#5 recap\n')
    assert parse_page_file(path)['scene_title'] == 'Issue#5 recap'


# --- page_aspect validation -------------------------------------------------

def test_invalid_page_aspect_flagged(tmp_path):
    body = '## Page architecture\nx\n## Image-generation workflow\nx\n'
    assert 'invalid_page_aspect' in _kinds(_write(tmp_path, body, 'page_aspect: widescreen\n'))


def test_non_portrait_without_justification_flagged(tmp_path):
    body = '## Page architecture\nx\n## Image-generation workflow\nx\n'
    assert 'non_portrait_page_aspect' in _kinds(_write(tmp_path, body, 'page_aspect: landscape\n'))


def test_non_portrait_with_justification_suppressed(tmp_path):
    body = '## Page architecture\nx\n## Image-generation workflow\nx\n'
    k = _kinds(_write(tmp_path, body, 'page_aspect: landscape  # double-page spread\n'))
    assert 'non_portrait_page_aspect' not in k


def test_portrait_aspect_no_finding(tmp_path):
    body = '## Page architecture\nx\n## Image-generation workflow\nx\n'
    k = _kinds(_write(tmp_path, body, 'page_aspect: portrait\n'))
    assert 'non_portrait_page_aspect' not in k
    assert 'invalid_page_aspect' not in k


# --- close-up convergence detection -----------------------------------------

_SCRIPT_3_PORTRAIT = """### Panel 1 — Mid, Lucien at the easel
Mid shot of Lucien.
### Panel 2 — Close, the portrait's mouth
Close on the portrait. The mouth, half-finished.
### Panel 3 — Close, the portrait's eyes
Close on the portrait. The eyes added.
### Panel 4 — Close, another stroke on the portrait
Close on the portrait. Another stroke.
"""


def test_detect_convergence_groups_same_subject():
    from storyforge.pages import detect_closeup_convergence
    groups = detect_closeup_convergence(_SCRIPT_3_PORTRAIT)
    assert groups == [[2, 3, 4]]


def test_detect_convergence_no_false_positive_different_subjects():
    from storyforge.pages import detect_closeup_convergence
    script = ("### Panel 1 — Close on the hand\nClose on the hand.\n"
              "### Panel 2 — Close on the candle\nClose on the candle.\n"
              "### Panel 3 — Close on the inkpot\nClose on the inkpot.\n")
    assert detect_closeup_convergence(script) == []


def test_detect_convergence_ignores_verb_close():
    from storyforge.pages import detect_closeup_convergence
    script = ("### Panel 1\nShe closes the book.\n"
              "### Panel 2\nHe closed the door.\n")
    assert detect_closeup_convergence(script) == []


def test_detect_convergence_numbered_beats_fallback():
    from storyforge.pages import detect_closeup_convergence
    script = ("1. Close on the portrait's mouth.\n"
              "2. Close on the portrait's eyes.\n")
    assert detect_closeup_convergence(script) == [[1, 2]]


def test_has_differentiation_language():
    from storyforge.pages import has_differentiation_language
    assert has_differentiation_language('one panel in isolation, one at the contact point')
    assert has_differentiation_language('vary the framing across panels')
    assert not has_differentiation_language('close on the portrait. another stroke.')


# --- undifferentiated-closeups validation -----------------------------------

def test_undifferentiated_closeups_flagged(tmp_path):
    body = ('## Panel script\n\n' + _SCRIPT_3_PORTRAIT +
            '\n## Image-generation workflow\n\n'
            '**Approach:** close on the portrait three times.\n')
    assert 'undifferentiated_closeups' in _kinds(_write(tmp_path, body))


def test_differentiated_closeups_not_flagged(tmp_path):
    body = ('## Panel script\n\n' + _SCRIPT_3_PORTRAIT +
            '\n## Image-generation workflow\n\n'
            '**Approach:** render one in isolation, one at the contact point, '
            'one at a different scale.\n')
    assert 'undifferentiated_closeups' not in _kinds(_write(tmp_path, body))


def test_no_workflow_no_closeup_warning(tmp_path):
    """A page not yet prompted (no workflow) is in-flight, not a finding."""
    body = '## Page architecture\nx\n## Panel script\n\n' + _SCRIPT_3_PORTRAIT
    assert 'undifferentiated_closeups' not in _kinds(_write(tmp_path, body))
