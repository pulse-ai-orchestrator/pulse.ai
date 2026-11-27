from __future__ import annotations

import itertools

import pytest

from pulse.domain.git_options import GitOption, GitOptions, InvalidGitOptions

ALL_FLAGS = list(itertools.product((False, True), repeat=3))


def _valid(worktree: bool, commits: bool, pull_request: bool) -> bool:
    return not pull_request or (worktree and commits)


@pytest.mark.parametrize(("worktree", "commits", "pull_request"), ALL_FLAGS)
def test_only_the_valid_combinations_can_be_built(worktree, commits, pull_request):
    """A pull request needs the run's branch and its commits; the other two stand alone."""
    if _valid(worktree, commits, pull_request):
        options = GitOptions(worktree, commits, pull_request)
        assert (options.use_worktree, options.atomic_commits, options.auto_pull_request) == (
            worktree,
            commits,
            pull_request,
        )
        return
    with pytest.raises(InvalidGitOptions):
        GitOptions(worktree, commits, pull_request)


@pytest.mark.parametrize(("worktree", "commits", "pull_request"), ALL_FLAGS)
def test_chained_drops_what_lacks_its_prerequisite(worktree, commits, pull_request):
    """Stored project flags are read safely: an orphan option counts as off, never on."""
    options = GitOptions.chained(
        use_worktree=worktree, atomic_commits=commits, auto_pull_request=pull_request
    )

    assert options.use_worktree == worktree
    assert options.atomic_commits == commits
    assert options.auto_pull_request == (worktree and commits and pull_request)


def test_switching_on_a_pull_request_switches_on_what_it_needs():
    options = GitOptions().toggled(GitOption.PULL_REQUEST)

    assert options == GitOptions(True, True, True)


def test_switching_off_the_branch_keeps_commits_and_drops_the_pull_request():
    options = GitOptions(True, True, True).toggled(GitOption.WORKTREE)

    assert options == GitOptions(False, True, False)


def test_switching_off_commits_keeps_the_branch_and_drops_the_pull_request():
    options = GitOptions(True, True, True).toggled(GitOption.COMMITS)

    assert options == GitOptions(True, False, False)


def test_switching_on_commits_leaves_the_branch_and_the_pull_request_off():
    options = GitOptions().toggled(GitOption.COMMITS)

    assert options == GitOptions(False, True, False)


def test_switching_on_the_branch_leaves_commits_off():
    options = GitOptions().toggled(GitOption.WORKTREE)

    assert options == GitOptions(True, False, False)


@pytest.mark.parametrize(("worktree", "commits", "pull_request"), ALL_FLAGS)
@pytest.mark.parametrize("option", list(GitOption))
def test_a_toggle_always_flips_its_option_and_stays_valid(worktree, commits, pull_request, option):
    if not _valid(worktree, commits, pull_request):
        return
    before = GitOptions(worktree, commits, pull_request)

    after = before.toggled(option)

    assert after.enabled(option) is not before.enabled(option)
