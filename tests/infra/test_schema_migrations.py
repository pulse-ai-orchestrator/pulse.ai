"""The schema carries a version, and each migration runs once, in order.

Without a version, every open re-inspected every table and an upgrade could
not tell a column the user's database never had from one it dropped; nor could
an older Pulse notice it was opening a database a newer one had changed.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

import pytest

from pulse.store.db import (
    MIGRATIONS,
    Migration,
    SchemaTooNewError,
    connect,
    migrate,
    schema_version,
)

LATEST = MIGRATIONS[-1].version


def _raw(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(str(path))
    connection.row_factory = sqlite3.Row
    return connection


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {str(row["name"]) for row in connection.execute(f"PRAGMA table_info({table})")}


def test_a_new_database_starts_at_the_latest_version(tmp_path: Path) -> None:
    """SCHEMA already has every change, so a fresh install replays none of them."""
    connect(tmp_path / "new.db").close()

    with _raw(tmp_path / "new.db") as connection:
        assert schema_version(connection) == LATEST
        assert "carried_seconds" in _columns(connection, "run_steps")


def test_a_database_already_at_version_2_gains_context_tokens(tmp_path: Path) -> None:
    """The column landed in migration 1 after version 2 had shipped, so an
    upgraded database never received the ALTER and every read of run_steps failed.
    """
    path = tmp_path / "v2.db"
    connect(path).close()
    with _raw(path) as connection:
        connection.execute("ALTER TABLE run_steps DROP COLUMN context_tokens")
        connection.execute("PRAGMA user_version = 2")

    connect(path).close()

    with _raw(path) as connection:
        assert schema_version(connection) == LATEST
        assert "context_tokens" in _columns(connection, "run_steps")


def test_a_database_from_before_versioning_gets_the_missing_columns(tmp_path: Path) -> None:
    """Version 0 is every database Pulse wrote before the schema had a version."""
    path = tmp_path / "old.db"
    connect(path).close()
    with _raw(path) as connection:
        connection.execute("ALTER TABLE run_steps DROP COLUMN carried_seconds")
        connection.execute("ALTER TABLE runs DROP COLUMN branch")
        connection.execute("PRAGMA user_version = 0")

    connect(path).close()

    with _raw(path) as connection:
        assert schema_version(connection) == LATEST
        assert "carried_seconds" in _columns(connection, "run_steps")
        assert "branch" in _columns(connection, "runs")


def _unversioned(path: Path) -> None:
    connect(path).close()
    with _raw(path) as connection:
        connection.execute("ALTER TABLE runs DROP COLUMN branch")
        connection.execute("PRAGMA user_version = 0")


def _open_together(path: Path, workers: int) -> list[sqlite3.Error]:
    start = threading.Barrier(workers, timeout=5)
    errors: list[sqlite3.Error] = []

    def open_database() -> None:
        start.wait()
        try:
            connect(path).close()
        except sqlite3.Error as error:
            errors.append(error)

    threads = [threading.Thread(target=open_database) for _ in range(workers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return errors


def test_connections_opened_together_on_an_old_database_migrate_it_once(tmp_path: Path) -> None:
    """The first daemon start after an upgrade serves concurrent requests, and each
    one opens the database: a migration that two of them run at once must not fail
    either request nor apply its change twice.
    """
    for attempt in range(5):
        path = tmp_path / f"old-{attempt}.db"
        _unversioned(path)

        assert _open_together(path, workers=4) == []
        with _raw(path) as connection:
            assert schema_version(connection) == LATEST
            assert "branch" in _columns(connection, "runs")


def test_a_migration_already_applied_is_not_run_again(tmp_path: Path) -> None:
    connection = _raw(tmp_path / "db.sqlite")
    migrate(connection)
    calls: list[int] = []

    def record(_connection: sqlite3.Connection) -> set[tuple[str, str]]:
        calls.append(1)
        return set()

    later = (*MIGRATIONS, Migration(version=LATEST + 1, apply=record))
    migrate(connection, later)
    migrate(connection, later)

    assert calls == [1]
    assert schema_version(connection) == LATEST + 1


def test_a_failed_migration_keeps_the_last_good_version(tmp_path: Path) -> None:
    """A crash halfway must not record a version whose change never landed."""
    connection = _raw(tmp_path / "db.sqlite")
    migrate(connection)

    def adds_then_breaks(conn: sqlite3.Connection) -> set[tuple[str, str]]:
        conn.execute("ALTER TABLE runs ADD COLUMN half_done TEXT")
        conn.execute("SELECT * FROM no_such_table")
        return set()

    with pytest.raises(sqlite3.OperationalError):
        migrate(connection, (*MIGRATIONS, Migration(version=LATEST + 1, apply=adds_then_breaks)))

    assert schema_version(connection) == LATEST
    assert "half_done" not in _columns(connection, "runs")


def test_a_migration_failing_outside_sqlite_releases_the_database(tmp_path: Path) -> None:
    """A bug in `apply` (a `KeyError`) left the write lock held until garbage collection.

    Every other connection, the daemon's included, then failed with `database is locked`.
    """
    path = tmp_path / "db.sqlite"
    connection = _raw(path)
    migrate(connection)

    def adds_then_bugs(conn: sqlite3.Connection) -> set[tuple[str, str]]:
        conn.execute("ALTER TABLE runs ADD COLUMN half_done TEXT")
        raise KeyError("bug in a migration")

    with pytest.raises(KeyError):
        migrate(connection, (*MIGRATIONS, Migration(version=LATEST + 1, apply=adds_then_bugs)))

    assert not connection.in_transaction
    other = sqlite3.connect(str(path), timeout=0)
    other.execute("BEGIN IMMEDIATE")
    other.rollback()
    other.close()
    assert "half_done" not in _columns(connection, "runs")
    assert schema_version(connection) == LATEST


def test_an_older_pulse_refuses_a_database_a_newer_one_migrated(tmp_path: Path) -> None:
    """Writing through a schema it does not know could corrupt the user's runs."""
    path = tmp_path / "future.db"
    connect(path).close()
    with _raw(path) as connection:
        connection.execute(f"PRAGMA user_version = {LATEST + 1}")

    with pytest.raises(SchemaTooNewError, match=f"version {LATEST + 1}"):
        connect(path)


def test_an_older_pulse_leaves_a_newer_database_untouched(tmp_path: Path) -> None:
    """Refusing after writing is too late: a table the newer schema dropped comes back."""
    path = tmp_path / "future.db"
    connect(path).close()
    with _raw(path) as connection:
        connection.execute("DROP TABLE run_events")
        connection.execute(f"PRAGMA user_version = {LATEST + 1}")

    with pytest.raises(SchemaTooNewError):
        connect(path)

    with _raw(path) as connection:
        tables = {str(row["name"]) for row in connection.execute("SELECT name FROM sqlite_master")}
        assert "run_events" not in tables


def test_versions_are_strictly_increasing() -> None:
    versions = [migration.version for migration in MIGRATIONS]

    assert versions == sorted(set(versions))
    assert versions[0] == 1


def test_a_database_at_version_3_gains_the_factory_pull_request_template(tmp_path: Path) -> None:
    """The PR body moved from engine code to `workflow_defs`; an upgraded database must
    get the factory template on its factory workflows, not an empty body.
    """
    path = tmp_path / "v3.db"
    connect(path).close()
    with _raw(path) as connection:
        connection.execute("ALTER TABLE workflow_defs DROP COLUMN pull_request_template")
        connection.execute("PRAGMA user_version = 3")

    connect(path).close()

    with _raw(path) as connection:
        assert schema_version(connection) == LATEST
        rows = connection.execute("SELECT id, pull_request_template FROM workflow_defs").fetchall()
        assert rows
        assert all("## Resumo" in str(row["pull_request_template"]) for row in rows)


def test_a_database_at_version_7_replaces_only_the_stock_pull_request_template(
    tmp_path: Path,
) -> None:
    """An upgrade moves the factory body forward and leaves a template the user edited."""
    from pulse.store.factory import previous_pull_request_template, pull_request_template

    path = tmp_path / "v7.db"
    connect(path).close()
    with _raw(path) as connection:
        connection.execute("PRAGMA user_version = 7")
        rows = connection.execute("SELECT id FROM workflow_defs ORDER BY id").fetchall()
        stock, edited = str(rows[0]["id"]), str(rows[1]["id"])
        connection.execute(
            "UPDATE workflow_defs SET pull_request_template = ? WHERE id = ?",
            (previous_pull_request_template(), stock),
        )
        connection.execute(
            "UPDATE workflow_defs SET pull_request_template = ? WHERE id = ?",
            ("editado pelo time", edited),
        )

    connect(path).close()

    with _raw(path) as connection:
        current = {
            str(row["id"]): str(row["pull_request_template"])
            for row in connection.execute("SELECT id, pull_request_template FROM workflow_defs")
        }

    assert current[stock] == pull_request_template()
    assert current[stock] != previous_pull_request_template()
    assert current[edited] == "editado pelo time"


def test_a_database_at_version_5_keys_artifacts_by_step_without_losing_any(tmp_path: Path) -> None:
    """With `(run_id, path)` as the key, a fix step editing the round file was never recorded."""
    path = tmp_path / "v5.db"
    connect(path).close()
    with _raw(path) as connection:
        connection.execute("DROP TABLE run_artifacts")
        connection.execute(
            "CREATE TABLE run_artifacts (run_id TEXT NOT NULL REFERENCES runs(id)"
            " ON DELETE CASCADE, path TEXT NOT NULL, step_id TEXT NOT NULL DEFAULT '',"
            " created_at TEXT NOT NULL, PRIMARY KEY (run_id, path))"
        )
        connection.execute(
            "INSERT INTO runs (id, workflow_id, workspace_root, created_at, updated_at)"
            " VALUES ('run-1', 'demo', '/tmp', 'now', 'now')"
        )
        connection.execute(
            "INSERT INTO run_artifacts VALUES ('run-1', 'reviews/round-001.md', 'review', 't1')"
        )
        connection.execute("PRAGMA user_version = 5")

    connect(path).close()

    with _raw(path) as connection:
        assert schema_version(connection) == LATEST
        connection.execute(
            "INSERT INTO run_artifacts VALUES ('run-1', 'reviews/round-001.md', 'fix', 't2')"
        )
        rows = connection.execute(
            "SELECT path, step_id, created_at FROM run_artifacts ORDER BY created_at"
        ).fetchall()
        assert [tuple(row) for row in rows] == [
            ("reviews/round-001.md", "review", "t1"),
            ("reviews/round-001.md", "fix", "t2"),
        ]


def test_a_database_at_version_6_opens_the_request_on_the_factory_step(tmp_path: Path) -> None:
    """An upgrade leaves factory rows in place, so the new column would stay off
    without a backfill. A later edit is not rewritten on the next open.
    """
    from pulse.store.workflow_defs import get_workflow

    path = tmp_path / "v6.db"
    connect(path).close()
    with _raw(path) as connection:
        connection.execute("ALTER TABLE workflow_steps DROP COLUMN opens_request")
        connection.execute("ALTER TABLE runs DROP COLUMN request_opened")
        connection.execute("PRAGMA user_version = 6")

    connect(path).close()

    upgraded = get_workflow("new-issue", db_path=path)
    assert upgraded is not None
    opened = {step.step_id: step.opens_request for step in upgraded.steps}
    assert opened["implement"] is True
    assert opened["verify"] is False
    quick = get_workflow("quick-fix", db_path=path)
    assert quick is not None
    assert all(not step.opens_request for step in quick.steps)
    with _raw(path) as connection:
        assert "request_opened" in _columns(connection, "runs")
        connection.execute(
            "UPDATE workflow_steps SET opens_request = 0 "
            "WHERE workflow_id = 'new-issue' AND step_id = 'implement'"
        )
        connection.commit()

    connect(path).close()

    again = get_workflow("new-issue", db_path=path)
    assert again is not None
    implement = next(step for step in again.steps if step.step_id == "implement")
    assert implement.opens_request is False


def test_a_run_stored_before_runs_kept_git_options_reads_none(tmp_path):
    """NULL options mean "follow the project", the behavior that run started with."""
    from pulse.store.runs import load_run

    db_path = tmp_path / "pulse.db"
    connection = connect(db_path)
    try:
        connection.execute(
            "INSERT INTO runs (id, workflow_id, workspace_root, created_at, updated_at)"
            " VALUES ('old', 'demo', '/tmp', 'now', 'now')"
        )
        connection.commit()
    finally:
        connection.close()

    loaded = load_run("old", db_path=db_path)

    assert loaded is not None
    assert loaded.git is None
