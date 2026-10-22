"""Stopped-service preparation preserves data while removing restored authority."""

import os
import sqlite3
import time
from pathlib import Path
from typing import cast

import pytest

from calendar_sync.application.operations.restoration import OfflineRestore, RestoreFailure
from calendar_sync.infrastructure.clock import SystemClock
from calendar_sync.infrastructure.persistence.connections import transaction
from calendar_sync.infrastructure.persistence.migrations import initialize_database
from calendar_sync.infrastructure.persistence.restoration import SqliteRestoreStore
from calendar_sync.infrastructure.security import CredentialCipher, ScryptPasswords
from tests.helpers import NOW
from tests.users import OTHER_USER, add_account, add_user


@pytest.fixture
def candidate(tmp_path: Path) -> tuple[Path, CredentialCipher, Path]:
    path = tmp_path / "restored.db"
    initialize_database(path)
    add_user(path)
    add_user(path, OTHER_USER, role="user")
    add_account(path, "account")
    cipher = CredentialCipher(CredentialCipher.generate_key())
    with transaction(path) as connection:
        connection.execute(
            "UPDATE connected_accounts SET encrypted_credentials=?",
            (cipher.encrypt('{"synthetic":"credential"}'),),
        )
        connection.execute("UPDATE installation_settings SET registration_policy='open'")
    parent = tmp_path / "private"
    parent.mkdir(mode=0o700)
    return path, cipher, parent / "before.db"


def test_prepare_requires_stopped_service_acknowledgement(
    candidate: tuple[Path, CredentialCipher, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    path, cipher, backup = candidate
    store = SqliteRestoreStore(path, cipher)

    def forbidden() -> None:
        pytest.fail("store accessed without acknowledgement")

    monkeypatch.setattr(store, "inspect", forbidden)
    with pytest.raises(RestoreFailure, match="services_not_acknowledged"):
        OfflineRestore(store, ScryptPasswords(), SystemClock()).prepare(
            backup, "user-1", "synthetic password", False
        )
    assert not backup.exists()


@pytest.mark.parametrize("administrator", ["missing", "user-2"])
def test_prepare_rejects_unknown_or_nonadministrator_selection(
    candidate: tuple[Path, CredentialCipher, Path], administrator: str
) -> None:
    path, cipher, backup = candidate
    before = path.read_bytes()
    with pytest.raises(RestoreFailure, match="administrator_invalid"):
        SqliteRestoreStore(path, cipher).prepare(backup, administrator, "new hash", NOW)
    assert not backup.exists()
    assert path.read_bytes() == before


def _rows(path: Path, query: str) -> tuple[tuple[object, ...], ...]:
    from contextlib import closing

    from calendar_sync.infrastructure.persistence.connections import open_connection

    with closing(open_connection(path, mode="ro")) as connection:
        return tuple(tuple(row) for row in connection.execute(query))


def test_prepare_creates_private_before_change_backup(
    candidate: tuple[Path, CredentialCipher, Path],
) -> None:
    from contextlib import closing

    from calendar_sync.infrastructure.persistence.connections import open_connection

    path, cipher, backup = candidate
    # Retain a connection so these committed rows exist in WAL rather than only the main file.
    with closing(open_connection(path, mode="rw")) as writer:
        writer.execute("INSERT INTO provider_sign_in_settings VALUES ('google',1)")
        writer.commit()
        assert Path(f"{path}-wal").stat().st_size > 0
        result = SqliteRestoreStore(path, cipher).prepare(backup, "user-1", "new hash", NOW)
    assert result.backup_path == backup
    assert backup.stat().st_mode & 0o777 == 0o600
    assert backup.parent.stat().st_mode & 0o777 == 0o700
    assert _rows(backup, "PRAGMA integrity_check") == (("ok",),)
    assert _rows(backup, "PRAGMA journal_mode") == (("delete",),)
    assert _rows(backup, "SELECT enabled FROM provider_sign_in_settings") == ((1,),)
    assert _rows(backup, "SELECT state FROM connected_accounts") == (("connected",),)
    assert not Path(f"{backup}-wal").exists()
    assert not Path(f"{backup}-shm").exists()
    assert (
        cipher.decrypt(
            cast(bytes, _rows(backup, "SELECT encrypted_credentials FROM connected_accounts")[0][0])
        )
        == '{"synthetic":"credential"}'
    )


@pytest.mark.parametrize(
    "kind", ["existing", "symlink", "hardlink", "source", "parent", "parent-symlink"]
)
def test_prepare_refuses_existing_aliased_and_symlink_backup_paths(
    candidate: tuple[Path, CredentialCipher, Path], kind: str
) -> None:
    import os

    path, cipher, backup = candidate
    if kind == "existing":
        backup.write_bytes(b"keep synthetic file")
    elif kind == "symlink":
        backup.symlink_to(path)
    elif kind == "hardlink":
        os.link(path, backup)
    elif kind == "source":
        backup = path
    elif kind == "parent":
        backup.parent.chmod(0o755)
    else:
        alias = backup.parent.parent / "alias"
        alias.symlink_to(backup.parent, target_is_directory=True)
        backup = alias / backup.name
    before = path.read_bytes()
    with pytest.raises(RestoreFailure, match="backup_unsafe"):
        SqliteRestoreStore(path, cipher).prepare(backup, "user-1", "hash", NOW)
    assert path.read_bytes() == before


@pytest.mark.parametrize(
    "boundary", ["copy", "validation", "file-fsync", "link", "unlink", "directory-fsync"]
)
def test_prepare_backup_failure_changes_nothing(
    candidate: tuple[Path, CredentialCipher, Path], monkeypatch: pytest.MonkeyPatch, boundary: str
) -> None:

    path, cipher, backup = candidate
    before = path.read_bytes()

    def fail(*_args: object, **_kwargs: object) -> None:
        raise OSError("synthetic failure")

    _inject_backup_failure(monkeypatch, boundary, fail)
    with pytest.raises(RestoreFailure, match="backup_failed"):
        SqliteRestoreStore(path, cipher).prepare(backup, "user-1", "hash", NOW)
    assert path.read_bytes() == before
    assert not backup.exists()
    assert list(backup.parent.iterdir()) == []


def test_prepare_rolls_back_every_change_on_failure(
    candidate: tuple[Path, CredentialCipher, Path],
) -> None:
    path, cipher, backup = candidate
    with transaction(path) as connection:
        connection.execute(
            "CREATE TRIGGER synthetic_failure BEFORE UPDATE ON connected_accounts "
            "BEGIN SELECT RAISE(ABORT, 'synthetic failure'); END"
        )
    before = _rows(path, "SELECT * FROM users")
    with pytest.raises(RestoreFailure, match="storage_failed"):
        SqliteRestoreStore(path, cipher).prepare(backup, "user-1", "new hash", NOW)
    assert backup.exists()
    assert _rows(path, "SELECT * FROM users") == before
    assert _rows(path, "SELECT * FROM installation_settings") == _rows(
        backup, "SELECT * FROM installation_settings"
    )
    assert _rows(path, "SELECT * FROM identity_email_readiness") == _rows(
        backup, "SELECT * FROM identity_email_readiness"
    )
    assert _rows(path, "SELECT * FROM connected_accounts") == _rows(
        backup, "SELECT * FROM connected_accounts"
    )


def _seed_authority(path: Path) -> str:
    from tests.users import USER, session_for

    token = session_for(path, USER)
    with transaction(path) as connection:
        connection.execute(
            "INSERT INTO invitations VALUES ('invite','invite-"
            "hash','user-1','2026-01-01','9999-01-01',NULL,NULL,NULL)"
        )
        connection.execute(
            "INSERT INTO integration_tokens VALUES "
            "('integration','user-1','synthetic','integration-"
            "hash','2026-01-01',NULL,NULL,'status')"
        )
        connection.execute(
            "INSERT INTO oauth_states VALUES "
            "('oauth','user-1','2026-01-01','9999-01-01',NULL,'google')"
        )
        connection.execute(
            "INSERT INTO password_reset_links VALUES ('reset','reset-"
            "hash','user-1','user-1','2026-01-01','9999-01-01',NULL,NULL,0)"
        )
        connection.execute(
            "INSERT INTO email_change_proofs VALUES "
            "('email','user-1','new@example.test',0,'email-"
            "hash','2026-01-01','9999-01-01',NULL,NULL)"
        )
        connection.execute(
            (
                "INSERT INTO registration_proofs VALUES (?, "
                "'new@example.test',NULL,'2026-01-01','9999-01-01',NULL,NULL)"
            ),
            ("a" * 64,),
        )
        connection.execute(
            "INSERT INTO provider_identities VALUES ('identity','user-1','google','ht"
            "tps://issuer.test','subject','2026-01-01')"
        )
        connection.execute("INSERT INTO provider_sign_in_settings VALUES ('google',1)")
        connection.execute(
            "INSERT INTO provider_flows VALUES ('flow','google','browser','9999-01-01',x'00',NULL)"
        )
        connection.execute(
            "INSERT INTO provider_pending_links VALUES "
            "(NULL,'pending','browser','9999-01-01',x'00')"
        )
        connection.execute(
            "INSERT INTO provider_link_flows SELECT "
            "'link','user-1',token_hash,0,'google','browser','9999-01-01',x'00',NULL "
            "FROM user_sessions"
        )
        connection.execute("UPDATE users SET email_verified=1")
        connection.execute(
            "UPDATE identity_email_readiness SET fingerprint='synthetic', tested_at='2026-01-01'"
        )
    return token


def test_prepare_revokes_all_bearer_proofs_and_provider_flows(
    candidate: tuple[Path, CredentialCipher, Path],
) -> None:
    from calendar_sync.infrastructure.persistence.users import SqliteSessions

    path, cipher, backup = candidate
    token = _seed_authority(path)
    result = SqliteRestoreStore(path, cipher).prepare(backup, "user-1", "hash", NOW)
    assert SqliteSessions(path, SystemClock()).user_of(token) is None
    for query in (
        "SELECT * FROM user_sessions",
        "SELECT * FROM oauth_states",
        "SELECT * FROM provider_flows",
        "SELECT * FROM provider_pending_links",
        "SELECT * FROM provider_link_flows",
        "SELECT * FROM provider_identities",
    ):
        assert _rows(path, query) == ()
    for query in (
        "SELECT revoked_at FROM invitations",
        "SELECT revoked_at FROM integration_tokens",
        "SELECT revoked_at FROM password_reset_links",
        "SELECT revoked_at FROM email_change_proofs",
        "SELECT revoked_at FROM registration_proofs",
    ):
        assert _rows(path, query) == ((NOW.isoformat(),),)
    assert _rows(path, "SELECT fingerprint,tested_at,generation FROM identity_email_readiness") == (
        (None, None, 1),
    )
    assert dict(result.invalidated_records)["provider_flows"] == 3


def test_prepare_replaces_admin_password_and_removes_provider_identities(
    candidate: tuple[Path, CredentialCipher, Path],
) -> None:
    path, cipher, backup = candidate
    _seed_authority(path)
    passwords = ScryptPasswords()
    with transaction(path) as connection:
        connection.execute(
            "UPDATE users SET password_hash=?", (passwords.hash("old synthetic password"),)
        )
    result = OfflineRestore(SqliteRestoreStore(path, cipher), passwords, SystemClock()).prepare(
        backup, "user-1", "new synthetic password", True
    )
    hashed = cast(str, _rows(path, "SELECT password_hash FROM users WHERE id='user-1'")[0][0])
    assert passwords.verify("new synthetic password", hashed)
    assert not passwords.verify("old synthetic password", hashed)
    assert result.disabled_users == 1
    assert _rows(
        path, "SELECT id,state,credential_revision,email_verified FROM users ORDER BY id"
    ) == (("user-1", "active", 1, 1), ("user-2", "disabled", 1, 1))
    assert (
        cipher.decrypt(
            cast(bytes, _rows(path, "SELECT encrypted_credentials FROM connected_accounts")[0][0])
        )
        == "{}"
    )
    assert _rows(path, "SELECT state,updated_at FROM connected_accounts")[0][0] == "disconnected"


def test_prepare_disables_provider_sign_in_before_auto_link(
    candidate: tuple[Path, CredentialCipher, Path],
) -> None:
    from calendar_sync.application.identity.provider_sign_in_ports import (
        AdmissionCommand,
        BeginIntent,
        BrowserProof,
        ProviderCallback,
        ProviderSignInRefused,
    )
    from calendar_sync.domain.provider_identity import ProviderClaims, ProviderIdentityKey
    from calendar_sync.infrastructure.persistence.provider_admission import SqliteProviderAdmission
    from calendar_sync.infrastructure.persistence.provider_flows import SqliteProviderFlows
    from tests.fakes.oidc import FixedClock

    path, cipher, backup = candidate
    _seed_authority(path)
    clock = FixedClock()
    flows = SqliteProviderFlows(path, CredentialCipher.generate_key(), clock, {"google": "config"})
    SqliteRestoreStore(path, cipher).prepare(backup, "user-1", "hash", NOW)
    # Even a fresh valid provider flow with matching verified claims cannot auto-link.
    browser = BrowserProof("b" * 43)
    flows.begin(BeginIntent("google", browser, None), "s" * 43)
    flow = flows.consume(ProviderCallback("google", "s" * 43, "code", browser))
    assert flow is not None
    claims = ProviderClaims(
        ProviderIdentityKey("https://issuer.test", "subject"), "user-1@example.test", True
    )
    with pytest.raises(ProviderSignInRefused):
        SqliteProviderAdmission(path, clock, flows, None).complete(
            AdmissionCommand(claims, flow, None)
        )
    assert _rows(path, "SELECT * FROM provider_identities") == ()
    assert _rows(path, "SELECT * FROM user_sessions") == ()


def _seed_sync_data(path: Path) -> None:
    from calendar_sync.infrastructure.security import token_hash

    add_account(path, "destination")
    with transaction(path) as connection:
        connection.execute(
            "INSERT INTO sync_rules (id,user_id,source_account_id,source_calendar_id,"
            "destination_account_id,destination_calendar_id,privacy_policy,all_day_po"
            "licy,busy_title,initial_lookback_days,state,awaiting_reauthorization,kee"
            "ps_place,plan_kept) VALUES ('rule','user-1','account','source','destinat"
            "ion','target','busy_only','include','Busy',30,'degraded',2,0,1)"
        )
        connection.execute(
            "INSERT INTO event_mappings (id,rule_id,user_id,source_account_id,source_"
            "calendar_id,source_event_id,destination_account_id,destination_calendar_"
            "id,destination_event_id,source_revision,projection_fingerprint) VALUES ("
            "'mapping','rule','user-1','account','source','series','destination','tar"
            "get','projection','revision','fingerprint')"
        )
        connection.execute(
            "INSERT INTO occurrence_mappings VALUES ('occurrence','mapping','user-1',"
            "'2026-10-01','account','source','source-"
            "occurrence','destination','target','target-"
            "occurrence','cancelled','revision',NULL)"
        )
        connection.execute("INSERT INTO sync_cursors VALUES ('rule','user-1','source-cursor')")
        connection.execute(
            "INSERT INTO destination_sync_cursors VALUES ('rule','user-1','destination-cursor')"
        )
        connection.execute("INSERT INTO pending_exception_replays VALUES ('mapping','user-1')")
        connection.execute(
            "INSERT INTO calendar_watches VALUES "
            "('watch','user-1','account','calendar:source',NULL,0)"
        )
        connection.execute("INSERT INTO watch_coverage VALUES ('watch','user-1','source')")
        connection.execute(
            (
                "INSERT INTO watch_registrations (id,watch_id,user_id,state,address,token"
                "_hash,created_at,requested_until,handle,expires_at) VALUES ('watch-regis"
                "tration','watch','user-1','live','https://calendar.example.test/api/v1/w"
                "atch-notices/google/watch-"
                "registration',?,'2026-01-01','9999-01-01','handle','9999-01-01')"
            ),
            (token_hash("watch-proof"),),
        )
        connection.execute(
            "INSERT INTO instant_sync_requests VALUES "
            "('rule','user-1',5,2,'2026-01-01','2026-01-01',NULL)"
        )
        connection.execute(
            "INSERT INTO delivery_evidence VALUES "
            "('google','https://calendar.example.test','2026-01-01',NULL)"
        )
        connection.execute(
            "INSERT INTO plans VALUES "
            "('synthetic','Synthetic',2,3,4,'five_minutes','2026-01-01','2026-01-01')"
        )
        connection.execute(
            "UPDATE installation_settings SET plans_enabled=1,default_plan_key='synthetic'"
        )
        connection.execute(
            "UPDATE users SET plan_key='synthetic',plan_assigned_by='administrator',p"
            "lan_assigner_id='user-1',plan_assigned_at='2026-01-01',plan_holds_at='20"
            "26-02-01',plan_grace_limit=2,plan_grace_admissions=3,plan_admissions=7"
        )
        connection.execute("INSERT INTO provider_sign_in_attempts VALUES (1,'begin','network',123)")
        connection.execute(
            "INSERT INTO reset_request_attempts VALUES (1,'invalid-token',123,NULL,'network',NULL)"
        )
        connection.execute(
            "INSERT INTO registration_request_attempts VALUES "
            "(1,'completion',123,NULL,'network',NULL)"
        )
        connection.execute("INSERT INTO email_change_attempts VALUES (1,'user-1',123,'target')")
        connection.execute(
            "INSERT INTO email_change_network_attempts VALUES (1,'completion','network',123)"
        )
        connection.execute(
            "INSERT INTO identity_email_test_attempts VALUES ('attempt','user-1','2026-01-01')"
        )


def _seal_accounts(path: Path, cipher: CredentialCipher) -> None:
    with transaction(path) as connection:
        connection.execute(
            "UPDATE connected_accounts SET encrypted_credentials=?", (cipher.encrypt("{}"),)
        )


def test_prepare_preserves_rules_mappings_and_all_plan_fields(
    candidate: tuple[Path, CredentialCipher, Path],
) -> None:
    path, cipher, backup = candidate
    _seed_sync_data(path)
    _seal_accounts(path, cipher)
    SqliteRestoreStore(path, cipher).prepare(backup, "user-1", "hash", NOW)
    for query in (
        "SELECT * FROM sync_rules",
        "SELECT * FROM event_mappings",
        "SELECT * FROM occurrence_mappings",
        "SELECT * FROM sync_cursors",
        "SELECT * FROM destination_sync_cursors",
        "SELECT * FROM pending_exception_replays",
        "SELECT * FROM plans",
        "SELECT plans_enabled,default_plan_key FROM installation_settings",
        (
            "SELECT id,plan_key,plan_assigned_by,plan_assigner_id,plan_assigned_at,pl"
            "an_holds_at,plan_grace_limit,plan_grace_admissions,plan_admissions FROM "
            "users ORDER BY id"
        ),
        "SELECT * FROM provider_sign_in_attempts",
        "SELECT * FROM reset_request_attempts",
        "SELECT * FROM registration_request_attempts",
        "SELECT * FROM email_change_attempts",
        "SELECT * FROM email_change_network_attempts",
        "SELECT * FROM identity_email_test_attempts",
    ):
        assert _rows(path, query) == _rows(backup, query)


def test_prepare_abandoned_watch_notice_cannot_queue_work(
    candidate: tuple[Path, CredentialCipher, Path],
) -> None:
    from calendar_sync.application.sync.watch_ports import NoticeKind, WatchNotice
    from calendar_sync.domain.accounts import ProviderKind
    from calendar_sync.domain.watches import WatchRegistrationId
    from calendar_sync.infrastructure.persistence.watch_inbox import SqliteWatchNoticeInbox

    path, cipher, backup = candidate
    _seed_sync_data(path)
    _seal_accounts(path, cipher)
    SqliteRestoreStore(path, cipher).prepare(backup, "user-1", "hash", NOW)
    notice = WatchNotice(
        WatchRegistrationId("watch-registration"), "watch-proof", "handle", NoticeKind.CHANGED
    )
    assert (
        SqliteWatchNoticeInbox(path).record(
            (notice,), ProviderKind.GOOGLE, "https://calendar.example.test", NOW
        )
        == 0
    )
    assert _rows(path, "SELECT requested_seq,handled_seq FROM instant_sync_requests") == ((5, 5),)
    assert _rows(path, "SELECT state FROM watch_registrations") == (("abandoned",),)
    assert _rows(path, "SELECT * FROM delivery_evidence") == ()


def test_prepare_is_safe_to_repeat(candidate: tuple[Path, CredentialCipher, Path]) -> None:
    path, cipher, backup = candidate
    _seed_authority(path)
    store = SqliteRestoreStore(path, cipher)
    store.prepare(backup, "user-1", "hash", NOW)
    store.prepare(backup.with_name("second.db"), "user-1", "another hash", NOW)
    with pytest.raises(RestoreFailure, match="backup_unsafe"):
        store.prepare(backup, "user-1", "third hash", NOW)
    assert _rows(path, "SELECT id,state,credential_revision FROM users ORDER BY id") == (
        ("user-1", "active", 2),
        ("user-2", "disabled", 2),
    )
    assert _rows(path, "SELECT registration_policy FROM installation_settings") == (
        ("invitation_only",),
    )
    assert _rows(path, "SELECT enabled FROM provider_sign_in_settings") == ((0,),)
    assert _rows(path, "SELECT revoked_at FROM invitations") == ((NOW.isoformat(),),)


@pytest.mark.parametrize("change", ["schema", "key"])
def test_prepare_refuses_schema_or_key_failure_before_backup(
    candidate: tuple[Path, CredentialCipher, Path], change: str
) -> None:
    path, cipher, backup = candidate
    if change == "schema":
        with transaction(path) as connection:
            connection.execute("DELETE FROM schema_migrations WHERE version=39")
    else:
        cipher = CredentialCipher(CredentialCipher.generate_key())
    before = path.read_bytes()
    with pytest.raises(RestoreFailure, match=r"schema_incompatible|key_mismatch"):
        SqliteRestoreStore(path, cipher).prepare(backup, "user-1", "hash", NOW)
    assert not backup.exists()
    assert path.read_bytes() == before


def test_prepare_refuses_change_during_backup(
    candidate: tuple[Path, CredentialCipher, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    from calendar_sync.infrastructure.persistence import restore_preparation

    path, cipher, backup = candidate
    from calendar_sync.infrastructure.persistence.restore_backup import publish_backup

    publish = publish_backup

    def changed(source: sqlite3.Connection, target: Path, key: CredentialCipher) -> None:
        publish(source, target, key)
        with transaction(path) as connection:
            connection.execute("UPDATE users SET credential_revision=8")

    monkeypatch.setattr(restore_preparation, "publish_backup", changed)
    with pytest.raises(RestoreFailure, match="database_changed"):
        SqliteRestoreStore(path, cipher).prepare(backup, "user-1", "hash", NOW)
    assert backup.exists()
    assert _rows(path, "SELECT state FROM connected_accounts") == (("connected",),)
    assert _rows(path, "SELECT password_hash FROM users WHERE id='user-1'") == (
        ("scrypt$unusable",),
    )


def test_prepare_backup_timeout_changes_nothing(
    candidate: tuple[Path, CredentialCipher, Path], monkeypatch: pytest.MonkeyPatch
) -> None:

    path, cipher, backup = candidate
    times = iter([0.0, 31.0])
    monkeypatch.setattr(time, "monotonic", lambda: next(times))
    with pytest.raises(RestoreFailure, match="backup_failed"):
        SqliteRestoreStore(path, cipher).prepare(backup, "user-1", "hash", NOW)
    assert not backup.exists()
    assert _rows(path, "SELECT state FROM connected_accounts") == (("connected",),)


def _inject_backup_failure(monkeypatch: pytest.MonkeyPatch, boundary: str, fail: object) -> None:
    from calendar_sync.infrastructure.persistence import restore_backup

    if boundary == "copy":
        monkeypatch.setattr(restore_backup, "_copy_database", fail)
    elif boundary == "validation":
        original = SqliteRestoreStore.inspect

        def inspect(store: SqliteRestoreStore) -> object:
            if store._database_path.name.startswith(".calendar-ghost-restore-"):
                raise RestoreFailure("integrity_failed")
            return original(store)

        monkeypatch.setattr(SqliteRestoreStore, "inspect", inspect)
    elif boundary == "file-fsync":
        monkeypatch.setattr(os, "fsync", fail)
    elif boundary == "link":
        monkeypatch.setattr(os, "link", fail)
    elif boundary == "unlink":
        _fail_first_unlink(monkeypatch)
    else:
        monkeypatch.setattr(restore_backup, "_sync_directory", fail)


def _fail_first_unlink(monkeypatch: pytest.MonkeyPatch) -> None:
    original_unlink = Path.unlink
    failed = False

    def unlink(target: Path, missing_ok: bool = False) -> None:
        nonlocal failed
        if target.name.startswith(".calendar-ghost-restore-") and not failed:
            failed = True
            raise OSError("synthetic interruption")
        original_unlink(target, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", unlink)


def test_prepare_locked_backup_destination_exits_without_writes(
    candidate: tuple[Path, CredentialCipher, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    from contextlib import closing

    from calendar_sync.infrastructure.persistence import restore_backup
    from calendar_sync.infrastructure.persistence.connections import open_connection

    path, cipher, backup = candidate
    copy_database = restore_backup._copy_database
    ticks = iter([0.0, 31.0])

    def locked_copy(source: sqlite3.Connection, temporary: Path) -> None:
        with closing(open_connection(temporary, mode="rw")) as locked:
            locked.execute("BEGIN EXCLUSIVE")
            monkeypatch.setattr(time, "monotonic", lambda: next(ticks))
            copy_database(source, temporary)

    monkeypatch.setattr(restore_backup, "_copy_database", locked_copy)
    with pytest.raises(RestoreFailure, match="backup_failed"):
        SqliteRestoreStore(path, cipher).prepare(backup, "user-1", "hash", NOW)
    assert not backup.exists()
    assert _rows(path, "SELECT registration_policy FROM installation_settings") == (("open",),)
    assert _rows(path, "SELECT state FROM connected_accounts") == (("connected",),)


def test_prepare_hashes_and_seals_before_write_lock(
    candidate: tuple[Path, CredentialCipher, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    path, cipher, backup = candidate
    passwords = ScryptPasswords()
    original_hash, original_encrypt = passwords.hash, cipher.encrypt
    observed: list[str] = []

    def assert_unlocked(operation: str) -> None:
        with transaction(path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            observed.append(operation)

    def hash_password(password: str) -> str:
        assert_unlocked("hash")
        return original_hash(password)

    def encrypt(value: str) -> bytes:
        assert_unlocked("encrypt")
        return original_encrypt(value)

    monkeypatch.setattr(passwords, "hash", hash_password)
    monkeypatch.setattr(cipher, "encrypt", encrypt)
    OfflineRestore(SqliteRestoreStore(path, cipher), passwords, SystemClock()).prepare(
        backup, "user-1", "new synthetic password", True
    )
    assert observed == ["hash", "encrypt"]


def test_prepare_old_token_and_proof_lookups_fail(
    candidate: tuple[Path, CredentialCipher, Path],
) -> None:
    from calendar_sync.infrastructure.identifiers import UuidIdGenerator
    from calendar_sync.infrastructure.integration_tokens import SqliteIntegrationTokens
    from calendar_sync.infrastructure.persistence.email_changes import SqliteEmailChangeProofs
    from calendar_sync.infrastructure.persistence.registration import (
        SqliteInvitations,
        SqlitePasswordResetLinks,
    )
    from calendar_sync.infrastructure.persistence.registration_proofs import (
        SqliteRegistrationProofs,
    )
    from calendar_sync.infrastructure.security import token_hash
    from tests.fake_calendar import FixedClock
    from tests.users import USER

    path, cipher, backup = candidate
    _seed_authority(path)
    clock, ids = FixedClock(), UuidIdGenerator()
    invitations = SqliteInvitations(path, ids, clock)
    resets = SqlitePasswordResetLinks(path, ids, clock)
    emails = SqliteEmailChangeProofs(path, ids, clock)
    registrations = SqliteRegistrationProofs(path, ids, clock)
    tokens = SqliteIntegrationTokens(path, clock, ids)
    issued = tokens.for_user(USER).issue("synthetic")
    with transaction(path) as connection:
        for statement in (
            "UPDATE invitations SET token_hash=?,expires_at='9999-01-01T00:00:00+00:00'",
            "UPDATE password_reset_links SET token_hash=?,expires_at='9999-01-01T00:00:00+00:00'",
            "UPDATE email_change_proofs SET token_hash=?,expires_at='9999-01-01T00:00:00+00:00'",
            "UPDATE registration_proofs SET token_hash=?,expires_at='9999-01-01T00:00:00+00:00'",
        ):
            connection.execute(statement, (token_hash("synthetic-proof"),))
    assert issued is not None
    assert tokens.authenticate(issued.token) is not None
    assert invitations.usable("synthetic-proof", NOW)
    assert resets.owner("synthetic-proof", NOW) == USER
    assert emails.check(USER, "synthetic-proof")
    assert registrations.check("synthetic-proof", "synthetic") is not None
    SqliteRestoreStore(path, cipher).prepare(backup, USER.value, "hash", NOW)
    assert tokens.authenticate(issued.token) is None
    assert not invitations.usable("synthetic-proof", NOW)
    assert resets.owner("synthetic-proof", NOW) is None
    assert not emails.check(USER, "synthetic-proof")
    assert registrations.check("synthetic-proof", "synthetic") is None


@pytest.mark.parametrize("field", ["created_at", "role", "state", "registration_policy"])
def test_prepare_refuses_malformed_persisted_fields_without_exposing_values(
    candidate: tuple[Path, CredentialCipher, Path], field: str
) -> None:
    path, cipher, backup = candidate
    marker = "synthetic-invalid-persisted-value"
    statements = {
        "created_at": "UPDATE users SET created_at=? WHERE id='user-1'",
        "role": "UPDATE users SET role=? WHERE id='user-1'",
        "state": "UPDATE users SET state=? WHERE id='user-1'",
        "registration_policy": "UPDATE installation_settings SET registration_policy=?",
    }
    # A malformed restored schema can retain its ledger while losing a field constraint.
    # Remove just that constraint to exercise conversion after normal SQLite inspection passes.
    checks = {
        "role": "CHECK (role IN ('installation_administrator', 'user'))",
        "state": "CHECK (state IN ('active', 'disabled'))",
        "registration_policy": (
            "CHECK (registration_policy IN ('only_me', 'invitation_only', 'open'))"
        ),
    }
    if field in checks:
        with transaction(path) as connection:
            connection.execute("PRAGMA writable_schema=ON")
            connection.execute(
                "UPDATE sqlite_master SET sql=replace(sql, ?, '') WHERE type='table' "
                "AND name IN ('users','installation_settings')",
                (checks[field],),
            )
            connection.execute("PRAGMA writable_schema=OFF")
    with transaction(path) as connection:
        connection.execute(statements[field], (marker,))
    store = SqliteRestoreStore(path, cipher)
    store.inspect()
    before = path.read_bytes()
    with pytest.raises(RestoreFailure, match=r"^schema_incompatible$") as failure:
        store.prepare(backup, "user-1", "hash", NOW)
    assert marker not in str(failure.value)
    assert failure.value.__suppress_context__
    assert not backup.exists()
    assert path.read_bytes() == before
