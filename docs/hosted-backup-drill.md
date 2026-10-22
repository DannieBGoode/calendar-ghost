# Synthetic hosted-backup compatibility record

2026-10-22, Darwin 27.0.0 arm64, Python 3.12.15. This is local file transport evidence, not a
measured remote RPO, hosted RTO, IAM/KMS test, 30-day retention test or durability guarantee.
The supported envelope is **stopped maintenance only**. Live compaction is unsafe with this pin.
See [the operating procedure](hosted-backups.md).

## Reproduction

The official `litestream-0.5.17-darwin-arm64.tar.gz` asset and release `checksums.txt` were fetched
from the [v0.5.17 release](https://github.com/benbjohnson/litestream/releases/tag/v0.5.17) into
`.context/litestream-v0.5.17/`, without a global install or runtime dependency.

```sh
shasum -a 256 .context/litestream-v0.5.17/litestream-0.5.17-darwin-arm64.tar.gz
.context/litestream-v0.5.17/litestream version
.venv/bin/python -m scripts.verify_hosted_backups \
  --litestream .context/litestream-v0.5.17/litestream --output-dir .context/hosted-drill-passwords
```

All three commands exited 0. Version output was `0.5.17`. The archive's SHA-256 matched the
published checksum `e211f68ff7658d19f193f2914417afdf8f89a053ff8f263e5d6b3b1d3bbc7b08`.
Extracted binary SHA-256 was `205b4c315d61a7f5709c4ab9001084eadfa8c9d36e1c198f9887417c2d88bb73`.
The output directory was new. Configuration kept the documented nested structure, changing only
paths/URL and snapshot interval/retention to 12s/24s, L0 retention/check to 2s/1s. Replica sync
remained 1s and default levels remained 30s/5m/1h. Each control socket had its own private directory.

The fixture used production migrations, two synthetic Users, three sealed Connected Accounts,
all bearer proof/flow types, enabled provider sign-in, watch and queued dispatch state, mappings,
and a Plan-held rule. No API server or second application writer started. Every SQLite open used
`connections.py`. Fixture databases, generated keys and raw terminal output are not committed.

## Required supported procedure

| Check | Observed result |
| --- | --- |
| Whole supported drill | Exit 0, 93.391 seconds |
| Database | 659,456 bytes, schema 39 |
| Initial marker UTC | `2026-10-22T20:03:04.158118+00:00` |
| Final marker UTC | `2026-10-22T20:04:33.546396+00:00` |
| Latest local marker sync | Maximum 0.056 seconds across 30 measured markers |
| Pre-maintenance sync | Source TXID 1, replica TXID 1, exit 0 |
| Stop before offline VACUUM | SIGTERM, exit 0 within 30 seconds |
| Same-path installed offline inspect | Exit 0 before compaction |
| Existing offline compact | Completed VACUUM and truncate checkpoint |
| Restart, new marker, sync, stop | Matching TXIDs; SIGTERM exit 0 |
| Fresh restores before/after maintenance | Exit 0, integrity and exact marker assertions pass |
| Installed inspect and prepare | Exits 0 and 0; prepare used a real controlling terminal |
| Restore plus inspect/prepare | 0.277 seconds combined |
| Conservative preparation | All authority invalidated; other User disabled with NULL password; accounts disconnected |
| Rules, mappings and Plans | Full restored fixture checked; Plan fields unchanged after preparation |
| Fresh metadata and new prefix | Older one-marker restore plus new marker restored correctly; original prefix unchanged |

Preparation used hidden confirmed synthetic password input through `pty.fork()` and the installed
`calendar-ghost-restore` console entry. Inspection used a plain subprocess. The operator interface
started no application, scheduler, mail, or provider adapters. The before-change backup had its own
mode-0700 directory; no password or key entered argv, evidence or committed output.

## Retention and failure input

Observed three initial L0 objects removed and six snapshots expired. Effective monitors reported
all default level intervals. L1 compacted on UTC boundaries `20:03:30.041`, `20:04:00.024`, and
`20:04:30.028`; this short run does not claim an observed hour of L3 operation.

Retained snapshots `000000000000001e` and `0000000000000022` restored with exits 0, integrity,
exact marker tuples captured independently at acknowledged source TXIDs (28 and 32 markers),
and installed offline inspection. Both include `initial` and `after-vacuum`; `1e` additionally
contains exactly `retention-00` through `retention-25`, and `22` through `retention-29`. Expired endpoints
`0000000000000004`, `0000000000000006`, `000000000000000a`, `000000000000000e`,
`0000000000000012`, and `0000000000000015` each returned exit 1 with
the pinned `Error: no matching backup files available` diagnostic, recorded as
`endpoint_unavailable`. Signals and generic operational errors fail the drill. The detached export
still passed integrity, exact marker and installed inspection checks after its own original live
endpoint `0000000000000004` returned the same classified unavailable diagnostic. This demonstrates
retention semantics with shortened intervals,
not 720 hours elapsed or an exact expiry deadline.

Stopping replication made the normal sync probe exit 1, exercising the failure input used by an
alarm. Actual remote delivery, five minutes of threshold time and monthly overdue-drill alerting
remain environment qualification requirements.

## Retained negative findings

A disposable live-compaction chain first restored correctly. Source integrity was `ok` before and
after `SqliteStorage.compact()` succeeded. Sync reported source TXID 2 and replica TXID 2;
SIGTERM and restore each exited 0. The restored database then failed integrity with
`database disk image is malformed`. Thus process success and TXID equality alone cannot establish
restore validity. This experiment is recorded as `live_compaction_compatible=false`, never as a
passing live-compatibility test. Its failed chain was not used by the supported procedure.

Earlier controlled artifacts are retained locally: `.context/full-control-no-compact` restored
successfully at TXID 1; `.context/full-control-compact` retained a valid source but produced the
malformed restored database at TXID 2. `.context/hosted-drill-4` additionally proved a fresh initial
restore immediately before the failing live VACUUM. An arbitrary two-second delay merely changed
the live outcome to StorageBusy in another run; it is not a fix or a supported readiness rule.
The implementation keeps existing StorageBusy behavior and its reader-blocked regression.

Separately, a copied replica with newer markers was pointed at an older one-marker database in a
disposable ahead-replica experiment. `replicate -once` exited 0, added one object, changed no existing
objects, and subsequent restore exited 0 but returned only the old `initial` marker. The original
prefix remained untouched. Production recovery therefore always uses fresh local metadata and a
new prefix, preserving the original through its retention.

The controller amended acceptance after focused external review: qualify the independently
verified stopped procedure, retain live compaction as a negative finding, and prohibit both
Clear activity (which may compact) and Reclaim space while Litestream runs. There is no storage
behavior change, new maintenance mode, or claim that later snapshots heal a damaged chain.
