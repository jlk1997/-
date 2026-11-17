"""Lightweight schema migration for dev — adds Phase 3 columns if missing.

DEPRECATED: prefer `alembic upgrade head`. Kept for one release to backfill columns
on databases that predate Alembic revisions.
"""
from sqlalchemy import inspect, text
from app.database import engine


MIGRATIONS = [
    ("users", "is_admin", "BOOLEAN DEFAULT FALSE"),
    ("users", "tenant_id", "VARCHAR(64) DEFAULT 'default'"),
    ("works", "storage_key", "VARCHAR(512)"),
    ("works", "cover_storage_key", "VARCHAR(512)"),
    ("works", "hls_url", "VARCHAR(512)"),
    ("works", "hls_storage_prefix", "VARCHAR(512)"),
    ("works", "tenant_id", "VARCHAR(64) DEFAULT 'default'"),
    ("posts", "tenant_id", "VARCHAR(64) DEFAULT 'default'"),
    ("posts", "challenge_id", "UUID"),
    ("provenance_records", "c2pa_manifest", "JSONB"),
    ("provenance_records", "blockchain_tx_hash", "VARCHAR(128)"),
    ("generation_jobs", "status_message", "TEXT"),
    ("generation_jobs", "phase", "VARCHAR(32)"),
    ("works", "preset_id", "VARCHAR(64)"),
    ("works", "reference_work_id", "UUID"),
    ("works", "allow_remix", "BOOLEAN DEFAULT TRUE"),
    ("works", "license", "VARCHAR(64) DEFAULT 'allow_remix'"),
    ("works", "post_process_status", "JSONB DEFAULT '{}'::jsonb"),
    ("user_api_keys", "scopes", "JSONB DEFAULT '[\"read\", \"generate\"]'::jsonb"),
    ("credit_transactions", "external_id", "VARCHAR(255)"),
    ("users", "is_tenant_admin", "BOOLEAN DEFAULT FALSE"),
    ("users", "referral_code", "VARCHAR(12)"),
    ("users", "referred_by_id", "UUID"),
    ("users", "terms_accepted_at", "TIMESTAMP"),
    ("users", "terms_version", "VARCHAR(32)"),
    ("users", "privacy_accepted_at", "TIMESTAMP"),
    ("users", "privacy_version", "VARCHAR(32)"),
    ("users", "ai_notice_accepted_at", "TIMESTAMP"),
    ("users", "wechat_privacy_authorized_at", "TIMESTAMP"),
    ("users", "analytics_consent", "BOOLEAN DEFAULT FALSE"),
    ("users", "deleted_at", "TIMESTAMP"),
    ("users", "deletion_scheduled_at", "TIMESTAMP"),
    ("works", "is_ai_generated", "BOOLEAN DEFAULT TRUE"),
    ("posts", "consent_at", "TIMESTAMP"),
    ("payment_orders", "payment_terms_version", "VARCHAR(32)"),
    ("payment_orders", "expires_at", "TIMESTAMP"),
    ("user_subscriptions", "plan_id", "VARCHAR(64)"),
    ("user_subscriptions", "channel", "VARCHAR(32)"),
    ("user_subscriptions", "cancel_at_period_end", "BOOLEAN DEFAULT FALSE"),
    ("user_subscriptions", "stripe_customer_id", "VARCHAR(255)"),
    ("users", "creator_level", "VARCHAR(32) DEFAULT 'standard'"),
    ("users", "kyc_status", "VARCHAR(20) DEFAULT 'none'"),
    ("users", "email_verified_at", "TIMESTAMP"),
    ("works", "release_status", "VARCHAR(32) DEFAULT 'none'"),
    ("works", "isrc", "VARCHAR(32)"),
    ("works", "commercial_cleared_at", "TIMESTAMP"),
    ("withdrawals", "receipt_no", "VARCHAR(40)"),
    ("listen_checkins", "station", "VARCHAR(32)"),
    ("vendor_keys", "inflight", "INTEGER DEFAULT 0"),
    ("vendor_keys", "daily_used", "INTEGER DEFAULT 0"),
    ("vendor_keys", "quota_date", "DATE"),
]


def run_migrations():
    inspector = inspect(engine)
    existing_tables = inspector.get_table_names()
    with engine.connect() as conn:
        for table, column, col_type in MIGRATIONS:
            if table not in existing_tables:
                continue
            existing_cols = {c["name"] for c in inspector.get_columns(table)}
            if column in existing_cols:
                continue
            try:
                conn.execute(text(f'ALTER TABLE "{table}" ADD COLUMN IF NOT EXISTS {column} {col_type}'))
                conn.commit()
            except Exception:
                conn.rollback()

        if "credit_transactions" in existing_tables:
            try:
                conn.execute(
                    text(
                        "CREATE UNIQUE INDEX IF NOT EXISTS uq_credit_tx_external_id "
                        "ON credit_transactions (external_id) WHERE external_id IS NOT NULL"
                    )
                )
                conn.commit()
            except Exception:
                conn.rollback()
        if "playlist_tracks" in existing_tables:
            try:
                conn.execute(
                    text("CREATE INDEX IF NOT EXISTS ix_playlist_tracks_playlist_id ON playlist_tracks (playlist_id)")
                )
                conn.commit()
            except Exception:
                conn.rollback()
        if "payment_orders" in existing_tables:
            try:
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_payment_orders_status_paid_at "
                        "ON payment_orders (status, paid_at)"
                    )
                )
                conn.commit()
            except Exception:
                conn.rollback()
        if "vendor_keys" in existing_tables:
            try:
                conn.execute(
                    text(
                        "DELETE FROM vendor_keys a USING vendor_keys b "
                        "WHERE a.ctid < b.ctid AND a.vendor = b.vendor "
                        "AND a.capability = b.capability AND a.key_prefix = b.key_prefix"
                    )
                )
                conn.execute(
                    text(
                        "CREATE UNIQUE INDEX IF NOT EXISTS uq_vendor_keys_vendor_cap_prefix "
                        "ON vendor_keys (vendor, capability, key_prefix)"
                    )
                )
                conn.commit()
            except Exception:
                conn.rollback()
        if "seat_jobs" in existing_tables:
            try:
                conn.execute(
                    text(
                        "DELETE FROM seat_jobs a USING seat_jobs b "
                        "WHERE a.kind <> 'upload' AND b.kind <> 'upload' "
                        "AND a.status IN ('queued', 'leased') AND b.status IN ('queued', 'leased') "
                        "AND a.seat_id = b.seat_id AND a.kind = b.kind AND a.ctid < b.ctid"
                    )
                )
                conn.execute(
                    text(
                        "CREATE UNIQUE INDEX IF NOT EXISTS uq_seat_job_open_non_upload "
                        "ON seat_jobs (seat_id, kind) "
                        "WHERE status IN ('queued', 'leased') AND kind <> 'upload'"
                    )
                )
                conn.commit()
            except Exception:
                conn.rollback()
        if "platform_metric_snapshots" in existing_tables:
            try:
                conn.execute(
                    text(
                        "CREATE UNIQUE INDEX IF NOT EXISTS uq_metric_user_work_channel_period_source "
                        "ON platform_metric_snapshots ("
                        "user_id, COALESCE(work_id, '00000000-0000-0000-0000-000000000000'::uuid), "
                        "channel_code, period_key, source)"
                    )
                )
                conn.commit()
            except Exception:
                conn.rollback()
