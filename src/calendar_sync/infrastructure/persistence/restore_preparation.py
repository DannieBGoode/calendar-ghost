"""Conservative preparation of a stopped installation, in one short transaction."""

import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

from calendar_sync.application.operations.restoration import (
    RestoreFailure,
    RestoreFailureCode,
    RestorePreparation,
)
from calendar_sync.domain.access import RegistrationPolicy, Role, User, UserId, UserState
from calendar_sync.domain.errors import DomainValidationError
from calendar_sync.domain.restoration import RestoreAuthority, RestoreDecision, decide_restoration
from calendar_sync.infrastructure.persistence.connections import open_connection
from calendar_sync.infrastructure.persistence.restoration import (
    SqliteRestoreStore,
    _check_integrity,
    _check_schema,
    _require_regular_file,
)
from calendar_sync.infrastructure.persistence.restore_backup import (
    publish_backup,
    require_backup_path,
)
from calendar_sync.infrastructure.security import CredentialCipher

# Table names are fixed in code, never operator input. Provider work is deleted before sessions
# because owned link flows refer to their owning sessions.
_DELETE = {
    RestoreAuthority.PROVIDER_FLOWS: (
        "DELETE FROM provider_flows",
        "DELETE FROM provider_pending_links",
        "DELETE FROM provider_link_flows",
    ),
    RestoreAuthority.SESSIONS: ("DELETE FROM user_sessions",),
    RestoreAuthority.OAUTH_STATES: ("DELETE FROM oauth_states",),
    RestoreAuthority.PROVIDER_IDENTITIES: ("DELETE FROM provider_identities",),
    RestoreAuthority.DELIVERY_EVIDENCE: ("DELETE FROM delivery_evidence",),
}
_REVOKE = {
    RestoreAuthority.INVITATIONS: "UPDATE invitations SET revoked_at=COALESCE(revoked_at, ?)",
    RestoreAuthority.INTEGRATION_TOKENS: (
        "UPDATE integration_tokens SET revoked_at=COALESCE(revoked_at, ?)"
    ),
    RestoreAuthority.REGISTRATION_PROOFS: (
        "UPDATE registration_proofs SET revoked_at=COALESCE(revoked_at, ?)"
    ),
    RestoreAuthority.RESET_LINKS: (
        "UPDATE password_reset_links SET revoked_at=COALESCE(revoked_at, ?)"
    ),
    RestoreAuthority.EMAIL_CHANGE_PROOFS: (
        "UPDATE email_change_proofs SET revoked_at=COALESCE(revoked_at, ?)"
    ),
}


def prepare_restored_database(
    database_path: Path,
    cipher: CredentialCipher,
    backup_path: Path,
    administrator_id: str,
    password_hash: str,
    at: datetime,
) -> RestorePreparation:
    SqliteRestoreStore(database_path, cipher).inspect()
    require_backup_path(database_path, backup_path)
    identity = database_path.stat()
    empty_credentials = cipher.encrypt("{}")
    try:
        with closing(open_connection(database_path, mode="rw")) as connection:
            version = connection.execute("PRAGMA data_version").fetchone()[0]
            _decision(connection, administrator_id)
            publish_backup(connection, backup_path, cipher)
            with connection:
                connection.execute("BEGIN IMMEDIATE")
                current = database_path.stat()
                _require_regular_file(database_path)
                if (current.st_dev, current.st_ino) != (
                    identity.st_dev,
                    identity.st_ino,
                ) or connection.execute("PRAGMA data_version").fetchone()[0] != version:
                    raise RestoreFailure("database_changed")
                _check_schema(connection)
                decision = _decision(connection, administrator_id)
                counts = _invalidate(connection, decision, at.isoformat())
                disabled, accounts = _prepare_owners(
                    connection, decision, password_hash, empty_credentials, at.isoformat()
                )
                _check_integrity(connection)
            return RestorePreparation(backup_path, disabled, accounts, tuple(counts))
    except sqlite3.Error as error:
        code = getattr(error, "sqlite_errorcode", 0) & 0xFF
        failure: RestoreFailureCode = (
            "storage_busy"
            if code in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED)
            else "storage_failed"
        )
        raise RestoreFailure(failure) from None
    except OSError:
        raise RestoreFailure("storage_failed") from None


def _decision(connection: sqlite3.Connection, administrator_id: str) -> RestoreDecision:
    row = connection.execute("SELECT * FROM users WHERE id=?", (administrator_id,)).fetchone()
    administrator = (
        None
        if row is None
        else User(
            UserId(row["id"]),
            row["email"],
            Role(row["role"]),
            UserState(row["state"]),
            datetime.fromisoformat(row["created_at"]),
        )
    )
    count = connection.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    settings = connection.execute(
        "SELECT registration_policy FROM installation_settings"
    ).fetchone()
    if settings is None:
        raise RestoreFailure("schema_incompatible")
    try:
        return decide_restoration(RegistrationPolicy(settings[0]), count, administrator)
    except DomainValidationError:
        raise RestoreFailure("administrator_invalid") from None


def _invalidate(
    connection: sqlite3.Connection, decision: RestoreDecision, at: str
) -> list[tuple[str, int]]:
    counts: dict[RestoreAuthority, int] = {}
    for authority, tables in _DELETE.items():
        if authority in decision.invalidate:
            counts[authority] = sum(connection.execute(table).rowcount for table in tables)
    for authority, table in _REVOKE.items():
        if authority in decision.invalidate:
            counts[authority] = connection.execute(table, (at,)).rowcount
    for authority, statement in _UPDATES.items():
        if authority in decision.invalidate:
            counts[authority] = connection.execute(statement).rowcount
    return [
        (authority.value, counts[authority])
        for authority in RestoreAuthority
        if authority in counts
    ]


_UPDATES = {
    RestoreAuthority.PROVIDER_SIGN_IN: "UPDATE provider_sign_in_settings SET enabled=0",
    RestoreAuthority.WATCH_REGISTRATIONS: "UPDATE watch_registrations SET state='abandoned'",
    RestoreAuthority.INSTANT_SYNC_REQUESTS: (
        "UPDATE instant_sync_requests SET handled_seq=requested_seq"
    ),
    RestoreAuthority.IDENTITY_EMAIL_READINESS: (
        "UPDATE identity_email_readiness SET fingerprint=NULL, tested_at=NULL, "
        "generation=generation+1"
    ),
}


def _prepare_owners(
    connection: sqlite3.Connection,
    decision: RestoreDecision,
    password_hash: str,
    empty_credentials: bytes,
    at: str,
) -> tuple[int, int]:
    connection.execute(
        "UPDATE installation_settings SET registration_policy=?",
        (decision.registration_policy.value,),
    )
    disabled = connection.execute(
        "UPDATE users SET state=?, credential_revision=credential_revision+1 WHERE id!=?",
        (decision.other_user_state.value, decision.administrator_id.value),
    ).rowcount
    connection.execute(
        "UPDATE users SET state=?, password_hash=?, "
        "credential_revision=credential_revision+1 WHERE id=?",
        (decision.administrator_state.value, password_hash, decision.administrator_id.value),
    )
    accounts = 0
    if decision.disconnect_accounts:
        accounts = connection.execute(
            "UPDATE connected_accounts SET encrypted_credentials=?, "
            "state='disconnected', updated_at=?",
            (empty_credentials, at),
        ).rowcount
    return disabled, accounts
