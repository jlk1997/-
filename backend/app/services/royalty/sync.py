"""Analytics sync: official CSV / OAuth / licensed API, plus authorized connector ingest."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.models.schemas import CreatorIdentityBinding, Release, ReleaseMetadata, User, Work
from app.services.distribution.adapters import ADAPTERS
from app.services.royalty import chartmetric, youtube


def list_analytics_sources(db: Session, user: User) -> dict:
    yt = (
        db.query(CreatorIdentityBinding)
        .filter(CreatorIdentityBinding.user_id == user.id, CreatorIdentityBinding.provider == "youtube")
        .first()
    )
    cm = (
        db.query(CreatorIdentityBinding)
        .filter(CreatorIdentityBinding.user_id == user.id, CreatorIdentityBinding.provider == "chartmetric")
        .first()
    )
    has_isrc = bool(
        db.query(ReleaseMetadata)
        .join(Release, Release.id == ReleaseMetadata.release_id)
        .filter(Release.owner_id == user.id, ReleaseMetadata.isrc.isnot(None))
        .first()
        or db.query(Work).filter(Work.owner_id == user.id, Work.isrc.isnot(None)).first()
    )
    partners = []
    for code, adapter in ADAPTERS.items():
        ready = adapter.configured()
        has_key = adapter.has_credentials()
        partners.append(
            {
                "id": f"{code}_api",
                "provider": code,
                "configured": ready,
                "usable_for_settlement": ready,
                "reason": "ok" if ready else ("configured_no_endpoint" if has_key else "not_configured"),
                "path": "partner_webhook" if ready else "official_csv",
            }
        )
    return {
        "sources": [
            {
                "id": "official_csv",
                "usable_for_settlement": True,
                "configured": True,
                "reason": "ok",
                "path": "upload",
                "hint": "distrokid_tunecore_routenote_cn",
            },
            {
                "id": "youtube",
                "usable_for_settlement": False,
                "configured": youtube.configured(),
                "bound": bool(yt and yt.official_token),
                "channel_id": yt.external_release_id if yt else None,
                "reason": "ok" if youtube.configured() else "not_configured",
                "path": "oauth",
            },
            {
                "id": "chartmetric",
                "usable_for_settlement": False,
                "configured": chartmetric.configured(),
                "has_isrc": has_isrc,
                "artist_id": cm.external_release_id if cm else None,
                "reason": "ok" if chartmetric.configured() else "not_configured",
                "path": "licensed_api",
            },
            *partners,
            {
                "id": "ops_connector",
                "usable_for_settlement": True,
                "configured": True,
                "reason": "ok",
                "path": "connector",
                "hint": "seat_harvest",
            },
            {
                "id": "user_connector",
                "usable_for_settlement": True,
                "configured": True,
                "reason": "ok",
                "path": "connector",
                "hint": "seat_harvest",
            },
            {
                "id": "seat_harvest",
                "usable_for_settlement": True,
                "configured": True,
                "reason": "ok",
                "path": "farm",
                "hint": "platform_and_user_seats",
            },
        ],
        "rules": {
            "no_server_password_login": True,
            "connector_requires_account_holder_session": True,
            "settlement_requires_ops_confirm_or_official_export": True,
        },
    }


def sync_partner_earnings(db: Session, user: User) -> list[dict]:
    from app.services.royalty.ingest import ingest_partner_rows

    results = []
    bindings = {
        row.provider: row
        for row in db.query(CreatorIdentityBinding).filter(CreatorIdentityBinding.user_id == user.id).all()
    }
    for code, adapter in ADAPTERS.items():
        if adapter.configured():
            rows = adapter.fetch_earnings()
            stored = ingest_partner_rows(db, user=user, source="distributor_api", rows=rows, usable=True) if rows else 0
            results.append({"source": "distributor_api", "provider": code, "synced": stored, "reason": "ok" if stored else "no_data"})
        binding = bindings.get(code)
        if binding and binding.official_token and adapter._base():
            rows = adapter.fetch_earnings(token=binding.official_token)
            stored = ingest_partner_rows(db, user=user, source="official_api", rows=rows, usable=False) if rows else 0
            results.append({"source": "official_api", "provider": code, "synced": stored, "reason": "ok" if stored else "no_data"})
    if results:
        db.commit()
    return results


def sync_platform_partner_earnings(db: Session) -> dict:
    """Pull configured partner earnings once and attach by ISRC across the catalog."""
    admin = db.query(User).filter(User.is_admin.is_(True)).first()
    actor = admin or db.query(User).order_by(User.created_at.asc()).first()
    if not actor:
        return {"synced": 0, "reason": "no_user"}
    rows = sync_partner_earnings(db, actor)
    from app.services.royalty.ingest import rematch_unattached_snapshots

    rematch = rematch_unattached_snapshots(db)
    return {
        "synced": sum(int(row.get("synced") or 0) for row in rows),
        "providers": rows,
        "rematched": rematch.get("matched") or 0,
    }


def sync_user_analytics(db: Session, user: User) -> dict:
    youtube_result = youtube.sync_user(db, user)
    chartmetric_result = chartmetric.sync_user(db, user)
    results = [youtube_result, chartmetric_result]
    extra = 0
    if chartmetric.configured():
        artist_result = chartmetric.sync_artist(db, user)
        results.append(artist_result)
        extra = int(artist_result.get("synced") or 0)
    partner_results = sync_partner_earnings(db, user)
    results.extend(partner_results)
    extra += sum(int(row.get("synced") or 0) for row in partner_results)
    return {
        "synced_at": datetime.utcnow().isoformat(),
        "results": results,
        "synced": int(youtube_result.get("synced") or 0) + int(chartmetric_result.get("synced") or 0) + extra,
    }


def sync_youtube_all(db: Session) -> dict:
    if not youtube.configured():
        return {"synced": 0, "reason": "not_configured"}
    rows = (
        db.query(CreatorIdentityBinding)
        .filter(CreatorIdentityBinding.provider == "youtube", CreatorIdentityBinding.status == "active")
        .limit(100)
        .all()
    )
    total = 0
    users = 0
    for row in rows:
        user = db.query(User).filter(User.id == row.user_id).first()
        if not user:
            continue
        result = youtube.sync_user(db, user)
        users += 1
        total += int(result.get("synced") or 0)
    return {"synced": total, "users": users, "reason": "ok"}


def sync_chartmetric_all(db: Session) -> dict:
    if not chartmetric.configured():
        return {"synced": 0, "reason": "not_configured"}
    user_ids = {
        r.owner_id
        for r in db.query(Release.owner_id)
        .join(ReleaseMetadata, ReleaseMetadata.release_id == Release.id)
        .filter(ReleaseMetadata.isrc.isnot(None))
        .distinct()
        .limit(50)
        .all()
    }
    user_ids |= {
        w.owner_id
        for w in db.query(Work.owner_id).filter(Work.isrc.isnot(None)).distinct().limit(50).all()
    }
    total = 0
    for uid in list(user_ids)[:50]:
        user = db.query(User).filter(User.id == uid).first()
        if not user:
            continue
        result = chartmetric.sync_user(db, user)
        total += int(result.get("synced") or 0)
    return {"synced": total, "users": len(user_ids), "reason": "ok"}


