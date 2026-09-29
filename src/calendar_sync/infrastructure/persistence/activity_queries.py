"""Questions about recorded Activity that both the Web API and rule health ask."""

from __future__ import annotations

import sqlite3

# A synchronization block. Recurring exclusions were recorded as conflicts before reason codes
# existed; they are skips.
_BLOCK = "{t}.action = 'conflict' AND COALESCE({t}.reason, '') != 'recurring_unsupported'"


def open_blocks(
    connection: sqlite3.Connection,
    *,
    rule_id: str | None = None,
    after: int | None = None,
    persisting: bool = False,
    run_id: str | None = None,
) -> list[tuple[int, str]]:
    """Entry and rule of each event whose latest decision was a block, newest first.

    Only blocks decided since each rule's latest daily pass count: that pass decides every blocked
    event again, so an older block it did not repeat, such as one of an occurrence whose series was
    deleted, is no longer open. That includes a block of an event that ended before the rule's sync
    window: the daily pass no longer lists it, and a past event no longer affects the destination
    calendar, so its block retires with it. `after` replaces the recorded pass with the audit
    identifier a pass began after, and `run_id` keeps only blocks that were that pass's own latest
    decision about their event, whatever other runs decided after it. A persisting
    block was already the event's latest decision before the pass began, so neither a failed
    attempt of the same pass nor a run interleaved with it counts as earlier evidence.
    """
    rules = (
        [rule_id]
        if rule_id is not None
        else [str(row[0]) for row in connection.execute("SELECT id FROM sync_rules")]
    )
    # With a named run, "latest" means that run's latest decision about the event, so a run
    # interleaved after it can neither hide nor supply the named run's verdict.
    same_run = "AND later.run_id = :run" if run_id is not None else ""
    # Rule Removal conflicts belong to a rule that no longer exists, so they are not blocks here.
    # Interpolates only constant SQL fragments and `?` placeholders; values stay bound.
    conditions = [
        "a.rule_id = :rule",
        "a.id > :floor",
        _BLOCK.format(t="a"),
        "a.source_event_id IS NOT NULL",
        f"""NOT EXISTS (
            SELECT 1 FROM audit_entries later
            WHERE later.rule_id = a.rule_id AND later.source_event_id = a.source_event_id
                AND later.id > a.id {same_run}
        )""",  # noqa: S608
    ]
    if run_id is not None:
        conditions.append("a.run_id = :run")
    if persisting:
        # Interpolates only constant SQL fragments and `?` placeholders; values stay bound.
        conditions.append(
            f"""(
                SELECT {_BLOCK.format(t="earlier")} FROM audit_entries earlier
                WHERE earlier.rule_id = a.rule_id AND earlier.source_event_id = a.source_event_id
                    AND earlier.id <= :floor
                ORDER BY earlier.id DESC LIMIT 1
            ) = 1"""  # noqa: S608
        )
    blocks: list[tuple[int, str]] = []
    for rule in rules:
        floor = after if after is not None else _checked_floor(connection, rule)
        blocks.extend(
            (int(row[0]), rule)
            # Interpolates only constant SQL fragments and `?` placeholders; values stay bound.
            for row in connection.execute(
                f"""
                SELECT a.id FROM audit_entries a INDEXED BY audit_entries_rule_id
                WHERE {" AND ".join(conditions)}
                """,  # noqa: S608
                {"rule": rule, "floor": floor, "run": run_id},
            )
        )
    return sorted(blocks, reverse=True)


def _checked_floor(connection: sqlite3.Connection, rule_id: str) -> int:
    row = connection.execute(
        "SELECT audit_floor FROM rule_block_checks WHERE rule_id = ?", (rule_id,)
    ).fetchone()
    return int(row[0]) if row else 0
