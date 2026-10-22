"""Assertions on restored synthetic state, independent of the operator command's output."""

from pathlib import Path
from typing import cast

from calendar_sync.infrastructure.security import CredentialCipher, ScryptPasswords
from scripts.hosted_backup_process import DrillFailure, rows


def assert_prepared(database: Path, before: Path, key: str) -> None:
    deleted = (
        "SELECT COUNT(*) FROM user_sessions",
        "SELECT COUNT(*) FROM oauth_states",
        "SELECT COUNT(*) FROM provider_identities",
        "SELECT COUNT(*) FROM provider_flows",
        "SELECT COUNT(*) FROM provider_pending_links",
        "SELECT COUNT(*) FROM provider_link_flows",
        "SELECT COUNT(*) FROM delivery_evidence",
    )
    revoked = (
        "SELECT COUNT(*) FROM invitations WHERE revoked_at IS NULL",
        "SELECT COUNT(*) FROM integration_tokens WHERE revoked_at IS NULL",
        "SELECT COUNT(*) FROM registration_proofs WHERE revoked_at IS NULL",
        "SELECT COUNT(*) FROM password_reset_links WHERE revoked_at IS NULL",
        "SELECT COUNT(*) FROM email_change_proofs WHERE revoked_at IS NULL",
    )
    for query in (*deleted, *revoked):
        if rows(database, query) != ((0,),):
            raise DrillFailure("restored authority remains")
    _assert_owner_state(database, key)
    for query in (
        "SELECT * FROM sync_rules",
        "SELECT * FROM event_mappings",
        "SELECT * FROM occurrence_mappings",
        "SELECT * FROM plans",
        "SELECT * FROM sync_cursors",
        "SELECT * FROM destination_sync_cursors",
        "SELECT plans_enabled,default_plan_key FROM installation_settings",
        "SELECT id,plan_key,plan_assigned_by,plan_assigner_id,plan_assigned_at,plan_holds_at,"
        "plan_grace_limit,plan_grace_admissions,plan_admissions FROM users ORDER BY id",
    ):
        if rows(database, query) != rows(before, query):
            raise DrillFailure("preserved state changed")


def _assert_owner_state(database: Path, key: str) -> None:
    expected = {
        "SELECT id,state FROM users ORDER BY id": (("user-1", "active"), ("user-2", "disabled")),
        "SELECT password_hash FROM users WHERE id!='user-1'": ((None,),),
        "SELECT registration_policy FROM installation_settings": (("invitation_only",),),
        "SELECT enabled FROM provider_sign_in_settings": ((0,),),
        "SELECT fingerprint,tested_at FROM identity_email_readiness": ((None, None),),
        "SELECT state FROM watch_registrations": (("abandoned",),),
        "SELECT requested_seq=handled_seq FROM instant_sync_requests": ((1,),),
    }
    for query, result in expected.items():
        if rows(database, query) != result:
            raise DrillFailure("prepared authority state differs")
    cipher = CredentialCipher(key)
    for state, sealed in rows(
        database, "SELECT state,encrypted_credentials FROM connected_accounts"
    ):
        if state != "disconnected" or cipher.decrypt(cast(bytes, sealed)) != "{}":
            raise DrillFailure("Connected Account authority remains")
    password = cast(str, rows(database, "SELECT password_hash FROM users WHERE id='user-1'")[0][0])
    if not ScryptPasswords().verify("synthetic recovery password", password):
        raise DrillFailure("fresh administrator password differs")


def assert_restored_state(source: Path, restored: Path) -> None:
    """Verify the fixture's state before any revocation can mask a missing restored row."""
    tables = (
        "users",
        "connected_accounts",
        "sync_rules",
        "event_mappings",
        "occurrence_mappings",
        "plans",
        "installation_settings",
        "identity_email_readiness",
        "user_sessions",
        "oauth_states",
        "invitations",
        "integration_tokens",
        "password_reset_links",
        "email_change_proofs",
        "registration_proofs",
        "provider_identities",
        "provider_flows",
        "provider_pending_links",
        "provider_link_flows",
        "provider_sign_in_settings",
        "watch_registrations",
        "instant_sync_requests",
        "delivery_evidence",
    )
    for table in tables:
        query = f"SELECT * FROM {table} ORDER BY rowid"  # noqa: S608 - fixed fixture table list
        if rows(source, query) != rows(restored, query):
            raise DrillFailure(f"restored fixture differs: {table}")
