"""`pulse-engine` parses its arguments strictly, like the `pulse` CLI.

A typo such as `--prot 9000` used to start the daemon on the default port, and
`--port abc` crashed with a traceback. A daemon on a port the user did not ask
for is worse than a usage error: the mistake only shows up later, elsewhere.
"""

from __future__ import annotations

import pytest

from pulse import __version__
from pulse.daemon import server
from pulse.store.paths import DEFAULT_HTTP_HOST, DEFAULT_HTTP_PORT


@pytest.fixture
def daemon_starts(monkeypatch) -> list[tuple[str, int]]:
    started: list[tuple[str, int]] = []
    monkeypatch.setattr(server, "run_daemon", lambda *, host, port: started.append((host, port)))
    return started


def test_help_describes_the_options_without_starting_the_daemon(daemon_starts, capsys):
    with pytest.raises(SystemExit) as exit_info:
        server.main(["--help"])

    out = capsys.readouterr().out
    assert exit_info.value.code == 0
    assert "--host" in out
    assert "--port" in out
    assert daemon_starts == []


def test_version_prints_the_package_version_without_starting_the_daemon(daemon_starts, capsys):
    with pytest.raises(SystemExit) as exit_info:
        server.main(["--version"])

    assert exit_info.value.code == 0
    assert capsys.readouterr().out == f"pulse-engine {__version__}\n"
    assert daemon_starts == []


@pytest.mark.parametrize(
    ("argv", "culprit"),
    [
        (["--prot", "9000"], "9000"),
        (["--prot=9000"], "--prot"),
        (["serve", "--prot", "9000"], "--prot"),
        (["start"], "start"),
        (["--port", "abc"], "abc"),
        (["--port", "0"], "0"),
        (["--port", "65536"], "65536"),
        (["--port"], "--port"),
    ],
)
def test_bad_arguments_are_a_usage_error_not_a_traceback(daemon_starts, capsys, argv, culprit):
    with pytest.raises(SystemExit) as exit_info:
        server.main(argv)

    err = capsys.readouterr().err
    assert exit_info.value.code == server.USAGE_ERROR
    assert culprit in err
    assert "Traceback" not in err
    assert daemon_starts == []


@pytest.mark.parametrize("argv", [[], ["serve"]])
def test_without_options_the_daemon_serves_on_the_defaults(daemon_starts, argv):
    assert server.main(argv) == 0
    assert daemon_starts == [(DEFAULT_HTTP_HOST, DEFAULT_HTTP_PORT)]


@pytest.mark.parametrize("argv", [["--port", "9000"], ["serve", "--port", "9000"]])
def test_the_requested_port_reaches_the_daemon(daemon_starts, argv):
    assert server.main(argv) == 0
    assert daemon_starts == [(DEFAULT_HTTP_HOST, 9000)]
