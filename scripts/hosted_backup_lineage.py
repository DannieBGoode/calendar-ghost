"""Disposable ahead-replica observation; never reuse a production replica prefix."""

import hashlib
import shutil
import subprocess
from contextlib import closing
from pathlib import Path
from typing import Any

from calendar_sync.infrastructure.persistence.connections import open_connection
from scripts.hosted_backup_process import Replication, rows


def manifest(prefix: Path) -> dict[str, str]:
    return {
        str(p.relative_to(prefix)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in prefix.rglob("*.ltx")
    }


def ahead_replica(replication: Replication, root: Path) -> dict[str, Any]:
    subject = root / "ahead-subject.db"
    with (
        closing(open_connection(root / "before-maintenance.db", mode="ro")) as source,
        closing(open_connection(subject)) as destination,
    ):
        source.backup(destination)
    copied = root / "disposable-ahead-prefix"
    shutil.copytree(replication.replica, copied)
    before = manifest(copied)
    config = root / "ahead.yml"
    config.write_text(f"dbs:\n  - path: {subject}\n    replica:\n      url: file://{copied}\n")
    attempted = subprocess.run(  # noqa: S603 - explicit pinned binary, disposable paths
        [str(replication.binary), "replicate", "-once", "-config", str(config)],
        capture_output=True,
        text=True,
        timeout=40,
    )
    after = manifest(copied)
    restored = root / "ahead-observed.db"
    recovery = subprocess.run(  # noqa: S603 - explicit pinned binary, disposable paths
        [str(replication.binary), "restore", "-o", str(restored), f"file://{copied}"],
        capture_output=True,
        text=True,
        timeout=40,
    )
    markers = (
        rows(restored, "SELECT value FROM drill_markers ORDER BY rowid")
        if recovery.returncode == 0
        else ()
    )
    return {
        "disposable_only": True,
        "replicate_once_exit": attempted.returncode,
        "restore_exit": recovery.returncode,
        "restored_markers": [row[0] for row in markers],
        "existing_objects_changed": sum(after.get(p) != value for p, value in before.items()),
        "new_objects": len(after.keys() - before.keys()),
    }
