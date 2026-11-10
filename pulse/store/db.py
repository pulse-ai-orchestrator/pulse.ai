from __future__ import annotations

import os
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from pulse.store.paths import GLOBAL_DB_FILE

SCHEMA = """
CREATE TABLE IF NOT EXISTS machine (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  version INTEGER NOT NULL,
  agent_binary TEXT NOT NULL,
  acp_command TEXT NOT NULL,
  auth_method TEXT NOT NULL,
  workspace_dir TEXT NOT NULL,
  model TEXT NOT NULL,
  permission_policy TEXT NOT NULL,
  completed_at TEXT,
  acp_test_passed INTEGER NOT NULL DEFAULT 0,
  default_agent TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS machine_agents (
  name TEXT PRIMARY KEY,
  binary TEXT NOT NULL,
  acp_command TEXT NOT NULL,
  models TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS machine_workflows (
  workflow_id TEXT PRIMARY KEY,
  agent TEXT,
  model TEXT
);

CREATE TABLE IF NOT EXISTS projects (
  id TEXT PRIMARY KEY,
  root_path TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS project_settings (
  project_id TEXT PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
  model TEXT,
  permission_policy TEXT,
  workspace_root TEXT,
  default_agent TEXT,
  use_worktree INTEGER NOT NULL DEFAULT 0,
  atomic_commits INTEGER NOT NULL DEFAULT 0,
  auto_pull_request INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS project_agents (
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  binary TEXT NOT NULL,
  acp_command TEXT NOT NULL,
  models TEXT NOT NULL,
  PRIMARY KEY (project_id, name)
);

CREATE TABLE IF NOT EXISTS project_workflows (
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  workflow_id TEXT NOT NULL,
  agent TEXT,
  model TEXT,
  PRIMARY KEY (project_id, workflow_id)
);

CREATE TABLE IF NOT EXISTS agent_settings (
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  agent_id TEXT NOT NULL,
  runtime TEXT,
  model TEXT,
  permission_policy TEXT,
  PRIMARY KEY (project_id, agent_id)
);

CREATE TABLE IF NOT EXISTS agent_sessions (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  workflow_id TEXT,
  agent_id TEXT,
  acp_session_id TEXT,
  status TEXT NOT NULL,
  started_at TEXT NOT NULL,
  ended_at TEXT
);

CREATE TABLE IF NOT EXISTS agent_defs (
  id TEXT PRIMARY KEY,
  label TEXT NOT NULL,
  runtime TEXT NOT NULL DEFAULT '',
  model TEXT NOT NULL DEFAULT '',
  permission_policy TEXT NOT NULL DEFAULT '',
  instructions TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS workflow_defs (
  id TEXT PRIMARY KEY,
  label TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  is_default INTEGER NOT NULL DEFAULT 0,
  default_prompt TEXT NOT NULL DEFAULT '',
  pull_request_template TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS workflow_steps (
  workflow_id TEXT NOT NULL REFERENCES workflow_defs(id) ON DELETE CASCADE,
  step_id TEXT NOT NULL,
  position INTEGER NOT NULL,
  label TEXT NOT NULL,
  agent_id TEXT NOT NULL,
  prompt_template TEXT NOT NULL DEFAULT '{{user_prompt}}',
  requires_approval INTEGER NOT NULL DEFAULT 0,
  fan_out INTEGER NOT NULL DEFAULT 0,
  requires_outcome INTEGER NOT NULL DEFAULT 1,
  repeat_from TEXT NOT NULL DEFAULT '',
  repeat_max INTEGER NOT NULL DEFAULT 0,
  commit_type TEXT NOT NULL DEFAULT '',
  opens_request INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (workflow_id, step_id)
);

CREATE TABLE IF NOT EXISTS runs (
  id TEXT PRIMARY KEY,
  workflow_id TEXT NOT NULL,
  workspace_root TEXT NOT NULL,
  user_prompt TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'pending',
  current_step TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  worktree_path TEXT NOT NULL DEFAULT '',
  branch TEXT NOT NULL DEFAULT '',
  branch_owned INTEGER NOT NULL DEFAULT 0,
  branch_base TEXT NOT NULL DEFAULT '',
  title TEXT NOT NULL DEFAULT '',
  description TEXT NOT NULL DEFAULT '',
  use_worktree INTEGER,
  atomic_commits INTEGER,
  auto_pull_request INTEGER,
  request_opened INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS runs_by_workspace
  ON runs (workspace_root, updated_at);

CREATE TABLE IF NOT EXISTS run_steps (
  run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
  step_id TEXT NOT NULL,
  position INTEGER NOT NULL DEFAULT 0,
  label TEXT NOT NULL DEFAULT '',
  agent_id TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'pending',
  summary TEXT NOT NULL DEFAULT '',
  acp_session_id TEXT NOT NULL DEFAULT '',
  started_at TEXT NOT NULL DEFAULT '',
  ended_at TEXT NOT NULL DEFAULT '',
  waiting_seconds REAL NOT NULL DEFAULT 0,
  rounds INTEGER NOT NULL DEFAULT 1,
  carried_seconds REAL NOT NULL DEFAULT 0,
  context_tokens INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (run_id, step_id)
);

CREATE TABLE IF NOT EXISTS run_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
  step_id TEXT NOT NULL DEFAULT '',
  acp_session_id TEXT NOT NULL DEFAULT '',
  kind TEXT NOT NULL,
  title TEXT NOT NULL,
  detail TEXT NOT NULL DEFAULT '',
  tool_id TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS run_events_by_run
  ON run_events (run_id, id);

CREATE TABLE IF NOT EXISTS run_artifacts (
  run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
  path TEXT NOT NULL,
  step_id TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  PRIMARY KEY (run_id, path, step_id)
);
"""


def default_db_path() -> Path:
    override = os.environ.get("PULSE_DB")
    if override:
        return Path(override)
    return GLOBAL_DB_FILE


ADDED_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("workflow_steps", "fan_out", "INTEGER NOT NULL DEFAULT 0"),
    ("workflow_defs", "default_prompt", "TEXT NOT NULL DEFAULT ''"),
    # On for existing databases too: steps that settled as `done` just by ending
    # the turn are exactly the ones that must now declare their outcome.
    ("workflow_steps", "requires_outcome", "INTEGER NOT NULL DEFAULT 1"),
    # An old run cannot tell how much of its time was waiting; zero is what it showed.
    ("run_steps", "waiting_seconds", "REAL NOT NULL DEFAULT 0"),
    # Off for existing databases: a worktree changes where the agent writes, and
    # that must never start happening because of an upgrade.
    ("project_settings", "use_worktree", "INTEGER NOT NULL DEFAULT 0"),
    # Empty is the truth for an old run: it ran in the project root, branch unknown.
    ("runs", "worktree_path", "TEXT NOT NULL DEFAULT ''"),
    ("runs", "branch", "TEXT NOT NULL DEFAULT ''"),
    # No step repeated before; a loop switched on by an upgrade would change the
    # cost of every run.
    ("workflow_steps", "repeat_from", "TEXT NOT NULL DEFAULT ''"),
    ("workflow_steps", "repeat_max", "INTEGER NOT NULL DEFAULT 0"),
    ("run_steps", "rounds", "INTEGER NOT NULL DEFAULT 1"),
    ("run_steps", "carried_seconds", "REAL NOT NULL DEFAULT 0"),
)


def _apply_context_tokens(connection: sqlite3.Connection) -> set[tuple[str, str]]:
    columns = (("run_steps", "context_tokens", "INTEGER NOT NULL DEFAULT 0"),)
    return _add_columns(connection, columns)


def _apply_git_options(connection: sqlite3.Connection) -> set[tuple[str, str]]:
    columns = (
        ("project_settings", "atomic_commits", "INTEGER NOT NULL DEFAULT 0"),
        ("project_settings", "auto_pull_request", "INTEGER NOT NULL DEFAULT 0"),
        ("workflow_steps", "commit_type", "TEXT NOT NULL DEFAULT ''"),
        ("runs", "branch_owned", "INTEGER NOT NULL DEFAULT 0"),
        ("runs", "branch_base", "TEXT NOT NULL DEFAULT ''"),
    )
    return _add_columns(connection, columns)


def _apply_pull_request_template(connection: sqlite3.Connection) -> set[tuple[str, str]]:
    columns = (("workflow_defs", "pull_request_template", "TEXT NOT NULL DEFAULT ''"),)
    return _add_columns(connection, columns)


def _apply_run_brief(connection: sqlite3.Connection) -> set[tuple[str, str]]:
    # NULL git options mark a run stored before runs kept their own: it keeps
    # following the project settings, as it did when it started.
    columns = (
        ("runs", "title", "TEXT NOT NULL DEFAULT ''"),
        ("runs", "description", "TEXT NOT NULL DEFAULT ''"),
        ("runs", "use_worktree", "INTEGER"),
        ("runs", "atomic_commits", "INTEGER"),
        ("runs", "auto_pull_request", "INTEGER"),
    )
    return _add_columns(connection, columns)


def _apply_opens_request(connection: sqlite3.Connection) -> set[tuple[str, str]]:
    columns = (
        ("workflow_steps", "opens_request", "INTEGER NOT NULL DEFAULT 0"),
        ("runs", "request_opened", "INTEGER NOT NULL DEFAULT 0"),
    )
    return _add_columns(connection, columns)


def _key_artifacts_by_step(connection: sqlite3.Connection) -> set[tuple[str, str]]:
    connection.execute(
        """
        CREATE TABLE run_artifacts_by_step (
          run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
          path TEXT NOT NULL,
          step_id TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL,
          PRIMARY KEY (run_id, path, step_id)
        )
        """
    )
    connection.execute(
        """
        INSERT INTO run_artifacts_by_step (run_id, path, step_id, created_at)
        SELECT run_id, path, step_id, created_at FROM run_artifacts
        WHERE run_id IN (SELECT id FROM runs)
        """
    )
    connection.execute("DROP TABLE run_artifacts")
    connection.execute("ALTER TABLE run_artifacts_by_step RENAME TO run_artifacts")
    return set()


def _add_columns(
    connection: sqlite3.Connection, columns: tuple[tuple[str, str, str], ...]
) -> set[tuple[str, str]]:
    added: set[tuple[str, str]] = set()
    for table, column, declaration in columns:
        pragma = f"PRAGMA table_info({table})"  # noqa: S608 - table is a constant
        existing = {str(row["name"]) for row in connection.execute(pragma)}
        if column not in existing:
            connection.execute(
                f"ALTER TABLE {table} ADD COLUMN {column} {declaration}"  # noqa: S608 - constants
            )
            added.add((table, column))
    return added


def _apply_added_columns(connection: sqlite3.Connection) -> set[tuple[str, str]]:
    """Apply missing `ALTER`s and return the columns added now.

    A new column gets the `ALTER` default on existing rows and factory seeding
    does not rerun on a seeded DB, so callers must backfill factory values.
    """
    return _add_columns(connection, ADDED_COLUMNS)


@dataclass(frozen=True)
class Migration:
    """One schema change, applied once, in order, inside its own transaction.

    `apply` returns the columns it added, so the factory backfill can tell an
    upgraded database from one that already had them.
    """

    version: int
    apply: Callable[[sqlite3.Connection], set[tuple[str, str]]]


class SchemaTooNewError(RuntimeError):
    """The database was migrated by a newer Pulse; this one must not touch it."""


# Version 1 is every column added before the schema had a version: databases
# from then report `user_version = 0` and may hold any subset of them. Append
# new migrations here and add the change to SCHEMA too, which builds fresh
# databases at the latest version without replaying history. SCHEMA also runs
# on existing databases before their migrations, so an index on a column a
# migration adds belongs in that migration, not in SCHEMA.
MIGRATIONS: tuple[Migration, ...] = (
    Migration(version=1, apply=_apply_added_columns),
    Migration(version=2, apply=_apply_git_options),
    Migration(version=3, apply=_apply_context_tokens),
    Migration(version=4, apply=_apply_pull_request_template),
    Migration(version=5, apply=_apply_run_brief),
    Migration(version=6, apply=_key_artifacts_by_step),
    Migration(version=7, apply=_apply_opens_request),
)


def schema_version(connection: sqlite3.Connection) -> int:
    return int(connection.execute("PRAGMA user_version").fetchone()[0])


def migrate(
    connection: sqlite3.Connection, migrations: tuple[Migration, ...] = MIGRATIONS
) -> set[tuple[str, str]]:
    """Bring the schema to the latest version and return the columns added.

    A database with no tables is new: SCHEMA already has every change, so it is
    stamped at the latest version. Each pending migration commits together with
    its version bump, so a crash halfway leaves the last good version recorded.
    """
    latest = migrations[-1].version if migrations else 0
    current = schema_version(connection)
    if current > latest:
        raise SchemaTooNewError(
            f"database schema is version {current}, this Pulse knows up to {latest}"
        )
    is_new = connection.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchone() is None
    connection.executescript(SCHEMA)
    if is_new:
        _set_version(connection, latest)
        connection.commit()
        return set()
    added: set[tuple[str, str]] = set()
    for migration in migrations:
        if migration.version <= current:
            continue
        # sqlite3 opens no implicit transaction before DDL, so an `ALTER` would
        # autocommit and survive a rollback. IMMEDIATE takes the write lock up
        # front: two connections that both read first and then `ALTER` deadlock,
        # and SQLite fails one of them instead of waiting.
        connection.execute("BEGIN IMMEDIATE")
        if schema_version(connection) >= migration.version:
            connection.rollback()
            continue
        try:
            added |= migration.apply(connection)
            _set_version(connection, migration.version)
            connection.commit()
        finally:
            # Any failure, not only sqlite3's: an open transaction keeps the write lock.
            if connection.in_transaction:
                connection.rollback()
    return added


def _set_version(connection: sqlite3.Connection, version: int) -> None:
    # PRAGMA takes no bound parameters; `version` is an int from MIGRATIONS.
    # The noqa is read by sast-lite, which flags any f-string query.
    connection.execute(f"PRAGMA user_version = {int(version)}")  # noqa: S608


def connect(path: Path | None = None) -> sqlite3.Connection:
    db_path = path or default_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(db_path))
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    added = migrate(connection)
    from pulse.store import factory

    if not factory.is_seeded(connection):
        factory.seed(connection)
    else:
        if ("workflow_defs", "default_prompt") in added:
            factory.backfill_default_prompts(connection)
        if ("workflow_steps", "commit_type") in added:
            factory.backfill_commit_types(connection)
        if ("workflow_defs", "pull_request_template") in added:
            factory.backfill_pull_request_templates(connection)
        if ("workflow_steps", "opens_request") in added:
            factory.backfill_opens_request(connection)
        factory.drop_approval_from_unattended_steps(connection)
        factory.inherit_policy_on_default_agent(connection)
        factory.drop_validation_from_implement(connection)
        factory.refresh_uncapped_clarify_loops(connection)
    connection.commit()
    return connection


def reset_default_path_cache() -> None:
    return None
