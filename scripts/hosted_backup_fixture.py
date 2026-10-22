"""Named, synthetic installation for the optional hosted backup compatibility drill."""

from pathlib import Path

from calendar_sync.infrastructure.persistence.connections import transaction
from calendar_sync.infrastructure.persistence.migrations import initialize_database
from calendar_sync.infrastructure.security import CredentialCipher


def build_synthetic_database(path: Path, master_key: str) -> None:
    """Create a multi-User installation without provider calls or production data."""
    initialize_database(path)
    cipher = CredentialCipher(master_key)
    with transaction(path) as connection:
        for identifier, role in (("user-1", "installation_administrator"), ("user-2", "user")):
            connection.execute(
                "INSERT INTO users (id,email,password_hash,role,state,created_at) "
                "VALUES (?,?,'scrypt$unusable',?,'active','2026-01-01')",
                (identifier, f"{identifier}@example.test", role),
            )
        for identifier, owner in (
            ("account", "user-1"),
            ("destination", "user-1"),
            ("other", "user-2"),
        ):
            connection.execute(
                "INSERT INTO connected_accounts (id,user_id,provider,display_name,email,"
                "encrypted_credentials,state,created_at,updated_at) "
                "VALUES (?,?,'google','Synthetic',?,?,'connected','2026-01-01','2026-01-01')",
                (
                    identifier,
                    owner,
                    f"{identifier}@example.test",
                    cipher.encrypt('{"synthetic":"credential"}'),
                ),
            )
        connection.execute("UPDATE installation_settings SET registration_policy='open'")
        connection.execute("CREATE TABLE drill_markers (value TEXT PRIMARY KEY, at TEXT NOT NULL)")
    _seed_authority(path)
    _seed_sync_data(path)


def _seed_authority(path: Path) -> None:
    with transaction(path) as connection:
        connection.execute(
            "INSERT INTO user_sessions VALUES "
            "('synthetic-session','user-1','2026-01-01','9999-01-01',NULL)"
        )
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


def _seed_sync_data(path: Path) -> None:
    from calendar_sync.infrastructure.security import token_hash

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
