"""Observe shortened retention using the same nested YAML and release-default levels."""

from __future__ import annotations

import json
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts.hosted_backup_process import (
    DrillFailure,
    Replication,
    checked,
    inspect_cli,
    marker,
    verify_markers,
)


def endpoints(replica: Path, level: int) -> dict[str, str]:
    return {str(p): p.stem.split("-")[1] for p in (replica / "ltx" / str(level)).glob("*.ltx")}


def retention_drill(replication: Replication, root: Path, env: dict[str, str]) -> dict[str, Any]:
    """Observe actual deletion, retained snapshot restoration, and a detached export."""
    replication.start()
    initial_l0 = set(endpoints(replication.replica, 0))
    snapshots: dict[str, str] = {}
    removed_snapshots: dict[str, str] = {}
    markers: list[str] = []
    states: dict[str, tuple[str, ...]] = {}
    max_lag = 0.0
    l1_seen = False
    # 90 seconds covers several default 30-second L1 boundaries and shortened snapshots.
    started = time.monotonic()
    exported: tuple[str, ...] | None = None
    export_txid = ""
    try:
        while time.monotonic() - started < 90:
            value = f"retention-{len(markers):02d}"
            written = time.monotonic()
            marker(replication.database, value)
            markers.append(value)
            sync = json.loads(replication.sync())
            states[f"{sync['txid']:016x}"] = ("initial", "after-vacuum", *markers)
            max_lag = max(max_lag, time.monotonic() - written)
            current = endpoints(replication.replica, 9)
            removed_snapshots.update({p: txid for p, txid in snapshots.items() if p not in current})
            snapshots.update(current)
            l1_seen |= bool(endpoints(replication.replica, 1))
            if exported is None:
                export_txid = f"{sync['txid']:016x}"
                exported = ("initial", "after-vacuum", *markers)
                replication.restore(root / "independent-export.db", exported)
            time.sleep(3)
    finally:
        stopped = replication.close()
    removed_l0 = initial_l0 - set(endpoints(replication.replica, 0))
    if not removed_l0 or not removed_snapshots or not l1_seen:
        raise DrillFailure("retention settings not demonstrated by L0, snapshots and default L1")
    boundaries = effective_configuration(replication)
    retained_results = restore_retained(replication, root, states, env)
    unavailable = expired_endpoints(replication, root, removed_snapshots)
    if exported is None:
        raise DrillFailure("independent export missing")
    export_expiry = verify_export(replication, root, exported, export_txid, env)
    # A stopped daemon must make the normal sync probe fail: the alert input is exercised.
    alarm = subprocess.run(  # noqa: S603 - explicit pinned executable, no shell
        [
            str(replication.binary),
            "sync",
            "-socket",
            str(replication.socket),
            "-wait",
            str(replication.database),
        ],
        capture_output=True,
        text=True,
        timeout=40,
    )
    if alarm.returncode == 0:
        raise DrillFailure("stopped replication probe did not fail")
    return {
        "markers": markers,
        "max_local_sync_seconds": round(max_lag, 3),
        "l0_objects_removed": len(removed_l0),
        "snapshots_expired": len(removed_snapshots),
        "default_l1_observed": l1_seen,
        "l1_boundary_utc": boundaries,
        "default_levels_seconds": [30, 300, 3600],
        "retained_snapshot_restores": retained_results,
        "expired_endpoint_attempts": unavailable,
        "independent_export_verified_after_expiry": True,
        "export_endpoint_expiry": export_expiry,
        "sigterm_exit": stopped,
        "stopped_probe_exit": alarm.returncode,
        "alarm_input_validated": True,
    }


def expired_endpoints(
    replication: Replication, root: Path, removed_snapshots: dict[str, str]
) -> list[dict[str, Any]]:
    unavailable = []
    for index, txid in enumerate(sorted(set(removed_snapshots.values()))):
        result = subprocess.run(  # noqa: S603 - explicit pinned executable, no shell
            [
                str(replication.binary),
                "restore",
                "-txid",
                txid,
                "-o",
                str(root / f"expired-{index}.db"),
                f"file://{replication.replica}",
            ],
            capture_output=True,
            text=True,
            timeout=40,
        )
        unavailable.append({"txid": txid, **endpoint_result(result)})
    if not any(item["reason"] == "endpoint_unavailable" for item in unavailable):
        raise DrillFailure("no expired endpoint became unavailable")
    return unavailable


def restore_retained(
    replication: Replication, root: Path, states: dict[str, tuple[str, ...]], env: dict[str, str]
) -> list[dict[str, Any]]:
    retained = endpoints(replication.replica, 9)
    if not retained:
        raise DrillFailure("no retained snapshot endpoints")
    retained_results = []
    for index, txid in enumerate(sorted(set(retained.values()))):
        target = root / f"retained-{index}.db"
        checked(
            [
                str(replication.binary),
                "restore",
                "-txid",
                txid,
                "-o",
                str(target),
                f"file://{replication.replica}",
            ]
        )
        if txid not in states:
            raise DrillFailure("retained endpoint has no acknowledged source state")
        verify_markers(target, states[txid])
        inspect_cli(target, env)
        retained_results.append({"txid": txid, "markers": len(states[txid]), "exit": 0})
    return retained_results


def verify_export(
    replication: Replication, root: Path, exported: tuple[str, ...], txid: str, env: dict[str, str]
) -> dict[str, Any]:
    target = root / "independent-export.db"
    verify_markers(target, exported)
    inspect_cli(target, env)
    result = subprocess.run(  # noqa: S603 - pinned explicit binary, no shell
        [
            str(replication.binary),
            "restore",
            "-txid",
            txid,
            "-o",
            str(root / "expired-export-point.db"),
            f"file://{replication.replica}",
        ],
        capture_output=True,
        text=True,
        timeout=40,
    )
    outcome = endpoint_result(result)
    if outcome["reason"] != "endpoint_unavailable":
        raise DrillFailure("export's original live endpoint did not expire")
    return {"txid": txid, **outcome}


def effective_configuration(replication: Replication) -> list[str]:
    log = replication.config.with_suffix(".log").read_text()
    for expected in (
        "level=1 interval=30s",
        "level=2 interval=5m0s",
        "level=3 interval=1h0m0s",
        "level=9 interval=12s",
        "interval=1s retention=2s",
    ):
        if expected not in log:
            raise DrillFailure("effective retention/compaction setting missing")
    boundaries = []
    for line in log.splitlines():
        if 'msg="compaction complete"' in line and "level=1 " in line:
            at = datetime.fromisoformat(line.split()[0].removeprefix("time="))
            if at.timestamp() % 30 < 1:
                boundaries.append(at.astimezone(UTC).isoformat())
    if not boundaries:
        raise DrillFailure("no observed default L1 compaction boundary")
    return boundaries


def endpoint_result(result: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    """Accept only the pinned restore-plan's specific missing-endpoint diagnostic."""
    if result.returncode == 0:
        return {"exit": 0, "reason": "available"}
    if (
        result.returncode == 1
        and result.stdout == ""
        and result.stderr.strip() == "Error: no matching backup files available"
    ):
        return {"exit": 1, "reason": "endpoint_unavailable"}
    raise DrillFailure("endpoint probe failed: signal or operational error")
