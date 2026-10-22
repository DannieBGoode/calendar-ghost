"""Explicit local-file compatibility drill for Litestream v0.5.17, never a remote SLA test."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from contextlib import closing
from pathlib import Path
from typing import Any

from calendar_sync.application.operations.errors import StorageBusy
from calendar_sync.infrastructure.persistence.connections import open_connection
from calendar_sync.infrastructure.persistence.storage import SqliteStorage
from calendar_sync.infrastructure.security import CredentialCipher
from scripts.hosted_backup_fixture import build_synthetic_database
from scripts.hosted_backup_process import (
    DrillFailure as DrillFailure,
)
from scripts.hosted_backup_process import (
    Replication as Replication,
)
from scripts.hosted_backup_process import (
    checked as checked,
)
from scripts.hosted_backup_process import (
    inspect_cli as inspect_cli,
)
from scripts.hosted_backup_process import (
    installed_cli as installed_cli,
)
from scripts.hosted_backup_process import (
    marker as marker,
)
from scripts.hosted_backup_process import (
    prepare_cli as prepare_cli,
)
from scripts.hosted_backup_process import (
    rows as rows,
)
from scripts.hosted_backup_process import (
    stop as stop,
)
from scripts.hosted_backup_process import (
    verify_markers as verify_markers,
)


def verify_prepared(database: Path, before: Path, key: str) -> None:
    from scripts.hosted_backup_assertions import assert_prepared

    assert_prepared(database, before, key)


def live_compaction_experiment(binary: Path, root: Path, database: Path) -> dict[str, Any]:
    """Disposable chain: a failed live restore must never contaminate the supported procedure."""
    import sqlite3

    subject = root / "live-subject.db"
    with (
        closing(open_connection(database, mode="ro")) as source,
        closing(open_connection(subject)) as destination,
    ):
        source.backup(destination)
    replication = Replication(binary, root, subject, "live-experiment")
    result: dict[str, Any] = {"compatible": False, "unsupported_experiment": True}
    replication.start()
    try:
        replication.restore(root / "before-live.db", ("initial",))
        result["initial_restore_exit"] = 0
        result["source_integrity_before"] = rows(subject, "PRAGMA integrity_check")[0][0]
        try:
            SqliteStorage(subject, busy_timeout=0.2).compact()
            result["compact"] = "success"
        except StorageBusy:
            result["compact"] = "StorageBusy"
        result["source_integrity_after"] = rows(subject, "PRAGMA integrity_check")[0][0]
        if result["source_integrity_before"] != "ok" or result["source_integrity_after"] != "ok":
            raise DrillFailure("live experiment source integrity failed")
        result["sync"] = json.loads(replication.sync())
    finally:
        result["sigterm_exit"] = replication.close()
    try:
        result["restore_process_exit"] = checked(
            [
                str(binary),
                "restore",
                "-o",
                str(root / "after-live.db"),
                f"file://{replication.replica}",
            ]
        ).returncode
        verify_markers(root / "after-live.db", ("initial",))
        result["compatible"] = True
    except sqlite3.DatabaseError as error:
        if str(error) != "database disk image is malformed" or result["compact"] != "success":
            raise
        result["restore_assertion"] = "failed: malformed database"
    return result


def maintenance(replication: Replication, root: Path, env: dict[str, str]) -> dict[str, Any]:
    replication.start()
    try:
        replication.restore(root / "before-maintenance.db", ("initial",))
        sync = replication.sync()
    finally:
        stopped = replication.close()
    inspect_cli(replication.database, env)
    SqliteStorage(replication.database, busy_timeout=0.2).compact()
    replication.start()
    try:
        marker(replication.database, "after-vacuum")
        replication.sync()
    finally:
        restarted = replication.close()
    replication.restore(root / "after-vacuum.db", ("initial", "after-vacuum"))
    return {
        "sync": json.loads(sync),
        "sigterm_exits": [stopped, restarted],
        "offline_inspect_exit": 0,
        "offline_compact": "success",
        "restores": [0, 0],
    }


def run_drill(binary: Path, output: Path) -> dict[str, Any]:
    if output.exists() and any(output.iterdir()):
        raise DrillFailure("output directory must be empty")
    version = checked([str(binary), "version"]).stdout.strip()
    if version != "0.5.17":
        raise DrillFailure("requires exactly v0.5.17")
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    root = output.resolve()
    started = time.monotonic()
    key = CredentialCipher.generate_key()
    env = {**os.environ, "CALENDAR_SYNC_MASTER_KEY": key}
    database = root / "source.db"
    build_synthetic_database(database, key)
    marker(database, "initial")
    replication = Replication(binary.resolve(), root, database, "live")
    evidence: dict[str, Any] = {
        "passed": False,
        "version": version,
        "transport": "local file",
        "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
    }
    try:
        evidence["live_compaction"] = live_compaction_experiment(binary.resolve(), root, database)
        evidence["maintenance"] = maintenance(replication, root, env)
        from scripts.hosted_backup_retention import retention_drill

        evidence["retention"] = retention_drill(replication, root, env)
        restored = root / "prepared.db"
        restore_started = time.monotonic()
        replication.restore(
            restored, ("initial", "after-vacuum", *evidence["retention"]["markers"])
        )
        evidence["inspect_exit"] = inspect_cli(restored, env)
        from scripts.hosted_backup_assertions import assert_restored_state

        assert_restored_state(database, restored)
        private = root / "protected"
        private.mkdir(mode=0o700)
        evidence["prepare_exit"] = prepare_cli(restored, private / "before.db", env)
        verify_prepared(restored, private / "before.db", key)
        evidence["restore_prepare_seconds"] = round(time.monotonic() - restore_started, 3)
        evidence["fresh_prefix"] = fresh_prefix(replication, root)
        from scripts.hosted_backup_lineage import ahead_replica

        evidence["disposable_ahead_replica"] = ahead_replica(replication, root)
        evidence["markers_utc"] = [
            list(row) for row in rows(database, "SELECT value,at FROM drill_markers ORDER BY rowid")
        ]
        evidence["database_bytes"] = database.stat().st_size
        evidence["elapsed_seconds"] = round(time.monotonic() - started, 3)
        evidence["supported_procedure_passed"] = True
        evidence["live_compaction_compatible"] = evidence["live_compaction"]["compatible"]
        evidence["passed"] = True
        evidence["acceptance_scope"] = "stopped-maintenance recovery only"
        return evidence
    finally:
        if replication.process is not None:
            replication.close()
        (root / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")


def fresh_prefix(replication: Replication, root: Path) -> dict[str, Any]:
    older = root / "recovered-older.db"
    with (
        closing(open_connection(root / "before-maintenance.db", mode="ro")) as source,
        closing(open_connection(older)) as destination,
    ):
        source.backup(destination)
    manifest = {
        str(p): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in replication.replica.rglob("*.ltx")
    }
    fresh = Replication(replication.binary, root, older, "recovered-new-prefix")
    fresh.start()
    try:
        marker(older, "fresh-lineage")
        fresh.sync()
    finally:
        code = fresh.close()
    fresh.restore(root / "fresh-restored.db", ("initial", "fresh-lineage"))
    if any(
        not Path(p).exists() or hashlib.sha256(Path(p).read_bytes()).hexdigest() != digest
        for p, digest in manifest.items()
    ):
        raise DrillFailure("original prefix changed")
    return {"original_prefix_unchanged": True, "sigterm_exit": code, "restore_exit": 0}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--litestream", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        evidence = run_drill(args.litestream, args.output_dir)
    except (DrillFailure, OSError, subprocess.SubprocessError) as error:
        print(f"drill failed: {error}", file=sys.stderr)
        return 1
    if not evidence["supported_procedure_passed"]:
        print("supported recovery passed; live compaction compatibility failed", file=sys.stderr)
        return 1
    print("supported stopped-maintenance drill passed; see live compaction finding in evidence")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
