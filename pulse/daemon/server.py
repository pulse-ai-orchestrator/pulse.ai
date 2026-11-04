from __future__ import annotations

import argparse
import contextlib
import logging
import os
import secrets
import signal
import socket
import sys
import threading
from collections.abc import Callable
from pathlib import Path
from types import FrameType

import uvicorn
from fastapi import FastAPI

from pulse import __version__
from pulse.api.app import create_app
from pulse.api.token_guard import TokenGuard
from pulse.daemon.logs import configure_logging
from pulse.daemon.runs import RunManager
from pulse.domain.control import SHUTDOWN_GRACE_SECONDS
from pulse.store.paths import (
    DAEMON_SOCKET,
    DEFAULT_HTTP_HOST,
    DEFAULT_HTTP_PORT,
    LOOPBACK_HOSTS,
    clear_daemon_meta,
    ensure_global_dir,
    write_daemon_meta,
)

SOCKET_MODE = 0o600
USAGE_ERROR = 2
SERVE_COMMAND = "serve"
MIN_PORT = 1
MAX_PORT = 65535
TOKEN_BYTES = 32
# Masks every permission bit SOCKET_MODE does not grant.
_SOCKET_UMASK = 0o777 & ~SOCKET_MODE
_log = logging.getLogger(__name__)


def _anchor_cwd() -> None:
    """Anchor the daemon in `~/.pulse` instead of the launcher's directory.

    The detached daemon would otherwise keep the launching terminal's cwd; if
    that project is deleted, macOS denies `getcwd()` (`EPERM`) and every new run
    fails. Runs always use an explicit `cwd`, so nothing is lost.
    """
    try:
        os.chdir(ensure_global_dir())
    except OSError:
        pass


def bind_private_socket(path: Path) -> socket.socket:
    """The daemon's Unix socket, connectable only by the user who started it.

    Whoever connects can start runs and answer their questions (AGENTS.md §6.1).
    uvicorn's own `bind_socket` makes the socket 0666 before anyone could tighten
    it, so Pulse binds it under a umask that keeps it private from the first
    instant. Changing the umask is process-wide; this runs before any server
    thread starts.
    """
    with contextlib.suppress(FileNotFoundError):
        path.unlink()
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    previous = os.umask(_SOCKET_UMASK)
    try:
        server.bind(str(path))
    except OSError:
        server.close()
        raise
    finally:
        os.umask(previous)
    os.chmod(path, SOCKET_MODE)
    return server


class GracefulServer(uvicorn.Server):
    """Stops the runs on the first SIGTERM/SIGINT, then lets uvicorn shut down.

    uvicorn replaces the process's signal handlers while it serves, and its
    shutdown waits for open connections: an attached client's SSE stream only
    ends when its run's bus closes. So the runs must stop first, or the daemon
    either hangs or exits leaving them `running`. They stop on their own
    thread: the handler runs on the event loop's thread, which may hold a lock
    the stop needs. A later signal keeps uvicorn's meaning: force the exit.
    """

    def __init__(self, config: uvicorn.Config, *, before_exit: Callable[[], None]) -> None:
        super().__init__(config)
        self._before_exit = before_exit
        self.stopping: threading.Thread | None = None

    def handle_exit(self, sig: int, frame: FrameType | None) -> None:
        if self.stopping is None:
            self.stopping = threading.Thread(
                target=self._stop_then_exit, args=(sig, frame), name="pulse-stop", daemon=True
            )
            self.stopping.start()
            return
        if self.stopping.is_alive():
            _log.warning("shutdown: forced before the runs stopped")
        self.force_exit = True
        super().handle_exit(sig, frame)

    def _stop_then_exit(self, sig: int, frame: FrameType | None) -> None:
        try:
            self._before_exit()
        finally:
            super().handle_exit(sig, frame)


def stop_runs(manager: RunManager, *, grace: float = SHUTDOWN_GRACE_SECONDS) -> None:
    left = manager.shutdown(grace=grace)
    if left:
        _log.warning("shutdown: runs still running after the grace period: %s", ", ".join(left))


def listener_configs(
    app: FastAPI, *, host: str, port: int, socket_path: Path, token: str
) -> tuple[uvicorn.Config, uvicorn.Config]:
    """The TCP and Unix-socket listeners: one app, a token only where the OS can't guard.

    The socket's `0600` already keeps other users out; TCP on loopback does
    not, so it demands the token kept in the `0600` meta file (ADR 0005).
    """
    tcp = uvicorn.Config(TokenGuard(app, token), host=host, port=port, log_level="warning")
    uds = uvicorn.Config(app, uds=str(socket_path), log_level="warning")
    return tcp, uds


def run_daemon(
    *,
    host: str = DEFAULT_HTTP_HOST,
    port: int = DEFAULT_HTTP_PORT,
    socket_path: Path | None = None,
) -> None:
    ensure_global_dir()
    _anchor_cwd()
    configure_logging()
    sock = socket_path or DAEMON_SOCKET
    manager = RunManager()
    app = create_app(manager)
    pid = os.getpid()
    token = secrets.token_urlsafe(TOKEN_BYTES)

    config_tcp, config_uds = listener_configs(
        app, host=host, port=port, socket_path=sock, token=token
    )
    tcp_socket = config_tcp.bind_socket()
    uds_socket = bind_private_socket(sock)
    write_daemon_meta(pid=pid, http_host=host, http_port=port, socket_path=sock, token=token)
    _log.info("daemon.started pid=%d http=%s:%d socket=%s", pid, host, port, sock)

    def _cleanup(*_args: object) -> None:
        clear_daemon_meta(pid)
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, _cleanup)
    signal.signal(signal.SIGINT, _cleanup)

    server_tcp = GracefulServer(config_tcp, before_exit=lambda: stop_runs(manager))
    server_uds = uvicorn.Server(config_uds)
    uds_thread = threading.Thread(
        target=server_uds.run, kwargs={"sockets": [uds_socket]}, name="pulse-uds", daemon=True
    )
    uds_thread.start()
    try:
        server_tcp.run(sockets=[tcp_socket])
    finally:
        server_uds.should_exit = True
        clear_daemon_meta(pid)
        _log.info("daemon.stopped pid=%d", pid)


def _tcp_port(value: str) -> int:
    try:
        port = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid port: {value!r}") from None
    if not MIN_PORT <= port <= MAX_PORT:
        raise argparse.ArgumentTypeError(f"port out of range {MIN_PORT}-{MAX_PORT}: {port}")
    return port


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pulse-engine",
        description="Pulse engine daemon: serves /api/* over a Unix socket and loopback TCP.",
    )
    parser.add_argument("--version", action="version", version=f"pulse-engine {__version__}")
    parser.add_argument("command", nargs="?", choices=[SERVE_COMMAND], help="Run in foreground")
    parser.add_argument(
        "--host", default=DEFAULT_HTTP_HOST, help=f"Loopback host (default: {DEFAULT_HTTP_HOST})"
    )
    parser.add_argument(
        "--port",
        type=_tcp_port,
        default=DEFAULT_HTTP_PORT,
        help=f"TCP port (default: {DEFAULT_HTTP_PORT})",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    host: str = args.host
    port: int = args.port
    # Off loopback the token would cross the network in clear text, and anyone on it could try it.
    if host not in LOOPBACK_HOSTS:
        allowed = ", ".join(LOOPBACK_HOSTS)
        sys.stderr.write(f"pulse-engine: refusing to listen on {host!r} (use one of {allowed})\n")
        return USAGE_ERROR
    run_daemon(host=host, port=port)
    return 0
