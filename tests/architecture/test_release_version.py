"""The release tag is the only place a version is written.

The release workflow tags `main` without committing back, so a version typed
into the source would drift from the tag the user installed.
"""

from __future__ import annotations

from importlib import metadata

import pulse


def test_package_version_is_the_version_the_build_derived_from_the_tag() -> None:
    assert pulse.__version__ == metadata.version("pulse-orchestrator")
