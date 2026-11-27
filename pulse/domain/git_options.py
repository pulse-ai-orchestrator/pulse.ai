"""How a run touches git: its own branch, a commit per delivery, a pull request."""

from __future__ import annotations

from dataclasses import dataclass, fields
from enum import StrEnum


class GitOption(StrEnum):
    WORKTREE = "use_worktree"
    COMMITS = "atomic_commits"
    PULL_REQUEST = "auto_pull_request"


# What each option needs switched on. Commits land on whatever branch the run
# works on, its own or the project's current one; a pull request publishes the
# run's own branch, so it needs both.
_REQUIRES: dict[GitOption, tuple[GitOption, ...]] = {
    GitOption.WORKTREE: (),
    GitOption.COMMITS: (),
    GitOption.PULL_REQUEST: (GitOption.WORKTREE, GitOption.COMMITS),
}


class InvalidGitOptions(ValueError):
    """An option switched on without the one it builds on."""


@dataclass(frozen=True)
class GitOptions:
    use_worktree: bool = False
    atomic_commits: bool = False
    auto_pull_request: bool = False

    def __post_init__(self) -> None:
        flags = self._flags()
        for option, needs in _REQUIRES.items():
            for needed in needs:
                if flags[option] and not flags[needed]:
                    raise InvalidGitOptions(f"{option} requires {needed}")

    @classmethod
    def chained(
        cls, *, use_worktree: bool, atomic_commits: bool, auto_pull_request: bool
    ) -> GitOptions:
        """Drop every option whose prerequisite is off, the safe reading of stored flags."""
        pull_request = use_worktree and atomic_commits and auto_pull_request
        return cls(use_worktree, atomic_commits, pull_request)

    def enabled(self, option: GitOption) -> bool:
        return self._flags()[option]

    def toggled(self, option: GitOption) -> GitOptions:
        """Flip `option`, carrying its dependencies along so the result is always valid.

        Switching on also switches on what it needs; switching off also
        switches off what needs it.
        """
        flags = self._flags()
        turning_on = not flags[option]
        flags[option] = turning_on
        if turning_on:
            for needed in _REQUIRES[option]:
                flags[needed] = True
        else:
            for each, needs in _REQUIRES.items():
                if option in needs:
                    flags[each] = False
        return GitOptions(**{str(key): value for key, value in flags.items()})

    def _flags(self) -> dict[GitOption, bool]:
        return {GitOption(item.name): bool(getattr(self, item.name)) for item in fields(self)}


NO_GIT_OPTIONS = GitOptions()
