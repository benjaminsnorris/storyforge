"""Regression tests for the pipeline review prompt (evals F-060).

The review that runs after extract got a diff summary but no file contents:
`git -C project diff --name-only` prints paths relative to the repo root, so
in a book nested inside a larger repo none of them resolved under the project
and nothing was inlined, while files outside the project (harness code,
FINDINGS.md) were listed. With no base branch the diff was empty. The model
then judged scenes from line counts and flagged uneven scene length.
"""

import os
import subprocess

import pytest

SCENE_TEXT = (
    'Marley was dead: to begin with. There is no doubt whatever about that. '
    'The register of his burial was signed by the clergyman.\n'
    'Scrooge knew he was dead? Of course he did. How could it be otherwise?\n'
)


def _git(cwd, *args):
    env = {
        **os.environ,
        'GIT_AUTHOR_NAME': 'Test', 'GIT_AUTHOR_EMAIL': 'test@test.com',
        'GIT_COMMITTER_NAME': 'Test', 'GIT_COMMITTER_EMAIL': 'test@test.com',
    }
    subprocess.run(['git', *args], cwd=cwd, capture_output=True, env=env, check=True)


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text)


def _project_files(project):
    _write(os.path.join(project, 'storyforge.yaml'),
           "project:\n  title: 'A Christmas Carol'\n  genre: 'ghost story'\n")
    _write(os.path.join(project, 'reference', 'scenes.csv'),
           'id|seq|title\nmarley-was-dead|1|Marley Was Dead\n')


@pytest.fixture
def nested_repo(tmp_path):
    """An evals-style repo: the book lives in projects/carol, and the session
    branch also changed files outside it."""
    repo = str(tmp_path / 'evals')
    project = os.path.join(repo, 'projects', 'carol')
    _project_files(project)
    _write(os.path.join(repo, 'README.md'), 'evals\n')
    _git(repo, 'init', '-b', 'main')
    _git(repo, 'add', '-A')
    _git(repo, 'commit', '-m', 'init')
    remote = str(tmp_path / 'remote.git')
    _git(str(tmp_path), 'init', '--bare', '-b', 'main', remote)
    _git(repo, 'remote', 'add', 'origin', remote)
    _git(repo, 'push', '-u', 'origin', 'main')
    _git(repo, 'checkout', '-b', 'pilot/carol')
    _write(os.path.join(project, 'scenes', 'marley-was-dead.md'), SCENE_TEXT)
    _write(os.path.join(repo, 'harness', 'run.py'), 'HARNESS_SECRET = 1\n')
    _write(os.path.join(repo, 'FINDINGS.md'), 'FINDINGS_OUTSIDE_PROJECT\n')
    _git(repo, 'add', '-A')
    _git(repo, 'commit', '-m', 'extract')
    return project


@pytest.fixture
def no_base_repo(tmp_path):
    """A repo whose only branch is the session branch: no main, no remote."""
    project = str(tmp_path / 'carol')
    _project_files(project)
    _write(os.path.join(project, 'scenes', 'marley-was-dead.md'), SCENE_TEXT)
    _git(project, 'init', '-b', 'storyforge/extract-20261030')
    _git(project, 'add', '-A')
    _git(project, 'commit', '-m', 'extract')
    return project


def _capture_prompt(project, monkeypatch, review_type='extraction'):
    """Run run_review_phase with every side effect stubbed; return the prompt."""
    import storyforge.api
    import storyforge.common
    import storyforge.git as sfgit

    prompts = []

    def fake_invoke(prompt, model, max_tokens=0, **kw):
        prompts.append(prompt)
        return '## Review\n\nok\n\n## Fixable Items\n\nNone.'

    monkeypatch.setattr(storyforge.api, 'invoke_api', fake_invoke)
    monkeypatch.setattr(sfgit, 'has_gh', lambda: False)
    monkeypatch.setattr(sfgit, 'commit_and_push', lambda *a, **kw: True)
    monkeypatch.setattr(sfgit, 'update_pr_task', lambda *a, **kw: None)
    monkeypatch.setattr(sfgit, 'get_coaching_level', lambda _: 'strict')
    monkeypatch.setattr(storyforge.common, 'get_current_cycle', lambda _: 0)
    sfgit.run_review_phase(review_type, project)
    assert len(prompts) == 1
    return prompts[0]


class TestReviewSeesContents:
    def test_nested_project_inlines_scene_contents(self, nested_repo, monkeypatch):
        prompt = _capture_prompt(nested_repo, monkeypatch)
        assert 'Marley was dead: to begin with.' in prompt
        assert 'scenes/marley-was-dead.md' in prompt

    def test_files_outside_project_are_not_reviewed(self, nested_repo, monkeypatch):
        prompt = _capture_prompt(nested_repo, monkeypatch)
        assert 'harness/run.py' not in prompt
        assert 'HARNESS_SECRET' not in prompt
        assert 'FINDINGS.md' not in prompt
        assert 'FINDINGS_OUTSIDE_PROJECT' not in prompt

    def test_earlier_reviews_and_logs_are_not_reviewed(self, no_base_repo, monkeypatch):
        _write(os.path.join(no_base_repo, 'working', 'reviews', 'pipeline-review-old.md'),
               'OLD_REVIEW_VERDICT: scenes are stubs\n')
        _write(os.path.join(no_base_repo, 'working', 'logs', 'extract.log'), 'OLD_LOG_LINE\n')
        prompt = _capture_prompt(no_base_repo, monkeypatch)
        assert 'OLD_REVIEW_VERDICT' not in prompt
        assert 'OLD_LOG_LINE' not in prompt
        assert 'Marley was dead: to begin with.' in prompt

    def test_non_ascii_scene_names_are_read(self, nested_repo, monkeypatch):
        repo = os.path.dirname(os.path.dirname(nested_repo))
        _write(os.path.join(nested_repo, 'scenes', 'café-scène-opens.md'), 'UNICODE_SCENE_BODY\n')
        _git(repo, 'add', '-A')
        _git(repo, 'commit', '-m', 'more')
        prompt = _capture_prompt(nested_repo, monkeypatch)
        assert 'scenes/café-scène-opens.md' in prompt
        assert 'UNICODE_SCENE_BODY' in prompt

    def test_no_base_branch_reviews_project_contents(self, no_base_repo, monkeypatch):
        prompt = _capture_prompt(no_base_repo, monkeypatch)
        assert '(no diff available)' not in prompt
        assert 'Marley was dead: to begin with.' in prompt
        assert 'no base branch' in prompt.lower()

    def test_word_counts_are_given(self, nested_repo, monkeypatch):
        prompt = _capture_prompt(nested_repo, monkeypatch)
        words = len(SCENE_TEXT.split())
        assert f'{words} words' in prompt


class TestReviewGuidance:
    def test_uneven_scene_length_is_not_a_defect(self, nested_repo, monkeypatch):
        prompt = _capture_prompt(nested_repo, monkeypatch).lower()
        assert 'uneven scene length' in prompt
        assert 'not a defect' in prompt

    def test_one_paragraph_per_line_is_not_a_stub(self, nested_repo, monkeypatch):
        prompt = _capture_prompt(nested_repo, monkeypatch).lower()
        assert 'one paragraph per line' in prompt
        assert 'stub' in prompt

    def test_extraction_has_its_own_criteria(self, nested_repo, monkeypatch):
        prompt = _capture_prompt(nested_repo, monkeypatch)
        assert 'Overall quality of the changes' not in prompt


class TestReviewBudget:
    def test_large_book_is_excerpted_within_budget(self, tmp_path, monkeypatch):
        import storyforge.git as sfgit

        project = str(tmp_path / 'big')
        _project_files(project)
        para = ('He walked on through the fog and the dark. ' * 40).strip()
        for i in range(300):
            _write(os.path.join(project, 'scenes', f'scene-event-{i:03d}.md'),
                   f'OPENING-{i:03d} ' + '\n'.join([para] * 20) + f' CLOSING-{i:03d}\n')
        _git(project, 'init', '-b', 'only')
        _git(project, 'add', '-A')
        _git(project, 'commit', '-m', 'extract')

        prompt = _capture_prompt(project, monkeypatch)
        assert len(prompt) < sfgit.REVIEW_CONTENT_BUDGET + 60000
        # Every file is at least named, with its size, even past the budget.
        for i in range(300):
            assert f'scenes/scene-event-{i:03d}.md' in prompt
        # Early files are excerpted (head shown, middle omitted), not skipped.
        assert 'OPENING-000' in prompt
        assert 'omitted' in prompt
        # Past the budget, files are named but not shown, and the prompt says so.
        assert 'not shown: the content budget ran out' in prompt
        # Reference CSVs come before scenes, so they are always shown.
        assert 'marley-was-dead|1|Marley Was Dead' in prompt


class TestFillLevel:
    def test_small_files_whole_large_files_share_the_rest(self):
        from storyforge.git import _fill_level
        # 100 + 200 fit; the two large files split the remaining 700.
        assert _fill_level([100, 200, 5000, 9000], 1000) == 350

    def test_everything_fits(self):
        from storyforge.git import _fill_level
        assert _fill_level([10, 20], 1000) >= 20

    def test_small_project_keeps_every_file(self, no_base_repo):
        from storyforge.git import review_file_sections
        _, contents = review_file_sections(no_base_repo, ['storyforge.yaml', 'reference/scenes.csv', 'scenes/marley-was-dead.md'])
        assert contents.count('=== FILE:') == 3
        assert 'omitted' not in contents
