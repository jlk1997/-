from __future__ import annotations

import csv
import hashlib
import io
import json
import uuid
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.schemas import (
    PlatformMetricSnapshot,
    Release,
    ReleaseMetadata,
    RoyaltyReportImport,
    User,
    Work,
)
from app.services.distribution.catalog import CONNECTOR_SOURCES, HARVEST_SOURCES, SETTLEMENT_SOURCES, normalize_store
from app.services.royalty.snapshots import upsert_metric_snapshot
from app.services.storage import get_storage_service

HEADER_ALIASES = {
    "isrc": {"isrc"},
    "upc": {"upc", "ean", "barcode"},
    "title": {
        "title",
        "track",
        "track_name",
        "song",
        "song_title",
        "song_name",
        "release_title",
        "video_title",
        "曲名",
        "歌曲名",
        "作品名",
        "视频标题",
    },
    "store": {"store", "store_name", "dsp", "platform", "channel", "retailer", "shop", "店铺", "平台"},
    "streams": {"streams", "plays", "play_count", "quantity", "units", "qty", "views", "播放", "播放量", "观看次数"},
    "saves": {"saves", "favorites", "listeners", "收藏", "听众"},
    "comments": {"comments", "comment_count", "评论"},
    "revenue": {
        "revenue",
        "earnings",
        "amount",
        "net",
        "royalty",
        "gross",
        "gross_earnings",
        "net_earnings",
        "earnings_usd",
        "net_receipts",
        "收益",
        "收入",
        "税后收益",
    },
    "currency": {"currency", "币种"},
    "period": {"period", "period_key", "month", "date", "period_start", "sale_month", "posted_date", "reporting_date", "账期"},
}


def _norm_header(name: str) -> str:
    raw = (name or "").strip().lower()
    for token in ("(usd)", "(cny)", "(eur)", "(gbp)", "（元）"):
        raw = raw.replace(token, "")
    return "".join(ch if ch.isalnum() else "_" for ch in raw).strip("_")


def _map_headers(headers: list[str]) -> dict[str, int]:
    mapped: dict[str, int] = {}
    for idx, raw in enumerate(headers):
        key = _norm_header(raw)
        for field, aliases in HEADER_ALIASES.items():
            if key in aliases:
                mapped[field] = idx
    return mapped


def _decode_report(content: bytes) -> str:
    if content.startswith(b"\xff\xfe") or content.startswith(b"\xfe\xff"):
        return content.decode("utf-16")
    for enc in ("utf-8-sig", "utf-16", "gbk"):
        try:
            return content.decode(enc)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="replace")


def _infer_default_channel(headers: list[str]) -> str | None:
    keys = {_norm_header(h) for h in headers}
    if {"spotify_uri", "spotify_id", "spotify"} & keys:
        return "spotify"
    if {"video_title", "watch_time_hours", "views"} & keys and "store" not in keys:
        return "youtube_music"
    if "listeners" in keys and "streams" in keys:
        return "spotify"
    return None


def _read_table(text: str) -> tuple[list[str], list[list[str]]]:
    last_error = "unrecognized report columns"
    for delim in (",", ";", "\t"):
        try:
            rows = list(csv.reader(io.StringIO(text), delimiter=delim))
        except csv.Error:
            continue
        for i, row in enumerate(rows[:25]):
            mapped = _map_headers(row)
            if len(mapped) >= 2 and ({"store", "title", "isrc"} & set(mapped)):
                return row, rows[i + 1 :]
        last_error = "unrecognized report columns"
    raise ValueError(last_error)


def revenue_to_minor(revenue: float, revenue_raw: str) -> int:
    raw = (revenue_raw or "").strip()
    if "." in raw:
        return int(round(revenue * 100))
    if abs(revenue) >= 100:
        return int(round(revenue))
    return int(round(revenue * 100))


def parse_report_csv(content: bytes) -> list[dict]:
    text = _decode_report(content)
    headers, body = _read_table(text)
    mapped = _map_headers(headers)
    default_channel = _infer_default_channel(headers)
    rows: list[dict] = []
    for raw in body:
        if not raw or all(not str(c).strip() for c in raw):
            continue

        def cell(field: str, default: str = "") -> str:
            idx = mapped.get(field)
            if idx is None or idx >= len(raw):
                return default
            return str(raw[idx]).strip()

        store = normalize_store(cell("store")) or default_channel
        revenue_raw = cell("revenue", "0").replace(",", "").replace("¥", "").replace("$", "").replace("€", "")
        try:
            revenue = float(revenue_raw or 0)
        except ValueError:
            revenue = 0.0
        revenue_minor = revenue_to_minor(revenue, revenue_raw)
        period = cell("period") or datetime.utcnow().strftime("%Y-%m")
        if len(period) >= 7 and period[4] == "-":
            period = period[:7]
        rows.append(
            {
                "isrc": cell("isrc") or None,
                "upc": cell("upc") or None,
                "title": cell("title") or None,
                "channel_code": store,
                "streams": _as_int(cell("streams")),
                "saves": _as_int(cell("saves")),
                "comments": _as_int(cell("comments")),
                "revenue_minor": revenue_minor,
                "currency": (cell("currency") or ("USD" if "$" in cell("revenue") else "CNY")).upper(),
                "period_key": period[:32],
            }
        )
    return rows


def _as_int(value: str) -> int:
    try:
        return int(float((value or "0").replace(",", "")))
    except ValueError:
        return 0


def _norm_isrc(value: str | None) -> str:
    return (value or "").replace("-", "").replace(" ", "").upper()


def _norm_title(value: str | None) -> str:
    return "".join(ch for ch in (value or "").lower() if ch.isalnum())


ISRC_REQUIRED_SOURCES = frozenset({"distributor_export", "distributor_api", "official_api", "user_export"})


def settlement_row_usable(*, source: str, release: Release | None, match_kind: str) -> bool:
    if source in {"first_party_radio", "first_party_radio_self"}:
        return False
    if source in HARVEST_SOURCES or source in CONNECTOR_SOURCES:
        return bool(match_kind)
    if source not in SETTLEMENT_SOURCES:
        return False
    if release and getattr(release, "mode", None) == "self_release":
        return False
    if source in ISRC_REQUIRED_SOURCES:
        return match_kind == "isrc"
    return True


def work_isrc_codes(db: Session, work: Work | None, release: Release | None) -> set[str]:
    codes: set[str] = set()
    if work and getattr(work, "isrc", None):
        codes.add(_norm_isrc(work.isrc))
    release_id = release.id if release else None
    if work and not release_id:
        from app.services.royalty.settlement import prefer_label_release

        release = prefer_label_release(db, work.id, release)
        release_id = release.id if release else None
    if release_id:
        meta = db.query(ReleaseMetadata).filter(ReleaseMetadata.release_id == release_id).first()
        if meta and meta.isrc:
            codes.add(_norm_isrc(meta.isrc))
    return {code for code in codes if code}


def isrc_matches_work(db: Session, work: Work | None, release: Release | None, row_isrc: str | None) -> bool:
    isrc = _norm_isrc(row_isrc)
    if not isrc or not work:
        return False
    return isrc in work_isrc_codes(db, work, release)


def resolve_work_match(
    db: Session, row: dict, default_user_id: uuid.UUID | None = None
) -> tuple[Work | None, Release | None, str]:
    work = None
    release = None
    raw_isrc = row.get("isrc")
    isrc = _norm_isrc(raw_isrc)
    if raw_isrc:
        candidates = [c for c in {raw_isrc, isrc, isrc.lower(), (raw_isrc or "").strip()} if c]
        if isrc:
            work = db.query(Work).filter(func.upper(func.replace(Work.isrc, "-", "")) == isrc).first()
        if not work and candidates:
            work = db.query(Work).filter(Work.isrc.in_(candidates)).first()
        if not work:
            meta = db.query(ReleaseMetadata).filter(ReleaseMetadata.isrc.in_(candidates)).first() if candidates else None
            if not meta and isrc:
                meta = (
                    db.query(ReleaseMetadata)
                    .filter(func.upper(func.replace(ReleaseMetadata.isrc, "-", "")) == isrc)
                    .first()
                )
            if meta:
                release = db.query(Release).filter(Release.id == meta.release_id).first()
                if release:
                    work = db.query(Work).filter(Work.id == release.work_id).first()
        if work:
            from app.services.royalty.settlement import prefer_label_release

            release = prefer_label_release(db, work.id, release)
            return work, release, "isrc"
    title = (row.get("title") or "").strip()
    if not work and title and default_user_id:
        work = (
            db.query(Work)
            .filter(Work.owner_id == default_user_id, func.lower(Work.title) == title.lower())
            .order_by(Work.created_at.desc())
            .first()
        )
        target = _norm_title(title)
        if not work and len(target) >= 4:
            candidates = (
                db.query(Work)
                .filter(Work.owner_id == default_user_id)
                .order_by(Work.created_at.desc())
                .limit(40)
                .all()
            )
            work = next((item for item in candidates if _norm_title(item.title) == target), None)
            if not work:
                work = next(
                    (
                        item
                        for item in candidates
                        if target in _norm_title(item.title) or _norm_title(item.title) in target
                    ),
                    None,
                )
    if work:
        from app.services.royalty.settlement import prefer_label_release

        release = prefer_label_release(db, work.id, release)
        return work, release, "title"
    return None, None, ""


def resolve_work(db: Session, row: dict, default_user_id: uuid.UUID | None = None) -> tuple[Work | None, Release | None]:
    work, release, _kind = resolve_work_match(db, row, default_user_id)
    return work, release


def rematch_unattached_snapshots(db: Session, user_id: uuid.UUID | None = None, *, limit: int = 200) -> dict:
    q = db.query(PlatformMetricSnapshot).filter(PlatformMetricSnapshot.work_id.is_(None))
    if user_id:
        q = q.filter(PlatformMetricSnapshot.user_id == user_id)
    rows = q.order_by(PlatformMetricSnapshot.created_at.desc()).limit(min(max(limit, 1), 400)).all()
    matched = 0
    for snap in rows:
        raw = dict(snap.raw or {})
        work, release, match_kind = resolve_work_match(db, raw, snap.user_id)
        if not work:
            continue
        try:
            with db.begin_nested():
                snap.work_id = work.id
                if release:
                    snap.release_id = release.id
                raw["rematched"] = True
                snap.raw = raw
                snap.usable_for_settlement = settlement_row_usable(
                    source=snap.source, release=release, match_kind=match_kind
                )
            matched += 1
        except Exception:
            continue
    if matched:
        db.commit()
    return {"checked": len(rows), "matched": matched}


def serialize_unattached_snapshot(snap: PlatformMetricSnapshot, suggested: Work | None = None) -> dict:
    raw = dict(snap.raw or {})
    return {
        "id": str(snap.id),
        "channel_code": snap.channel_code,
        "period_key": snap.period_key,
        "source": snap.source,
        "streams": snap.streams or 0,
        "saves": snap.saves or 0,
        "revenue_minor": snap.revenue_minor or 0,
        "currency": snap.currency or "CNY",
        "usable_for_settlement": bool(snap.usable_for_settlement),
        "title": raw.get("title"),
        "isrc": raw.get("isrc"),
        "suggested_work_id": str(suggested.id) if suggested else None,
        "suggested_title": suggested.title if suggested else None,
        "created_at": snap.created_at.isoformat() if snap.created_at else None,
    }


def list_unattached_snapshots(db: Session, user: User, *, limit: int = 50) -> list[dict]:
    rematch_unattached_snapshots(db, user.id)
    rows = (
        db.query(PlatformMetricSnapshot)
        .filter(PlatformMetricSnapshot.user_id == user.id, PlatformMetricSnapshot.work_id.is_(None))
        .order_by(PlatformMetricSnapshot.created_at.desc())
        .limit(min(max(limit, 1), 100))
        .all()
    )
    works = (
        db.query(Work)
        .filter(Work.owner_id == user.id)
        .order_by(Work.created_at.desc())
        .limit(80)
        .all()
    )
    by_title = {(work.title or "").strip().lower(): work for work in works if (work.title or "").strip()}
    by_isrc = {_norm_isrc(work.isrc): work for work in works if work.isrc}
    out: list[dict] = []
    for snap in rows:
        raw = dict(snap.raw or {})
        title = (raw.get("title") or "").strip().lower()
        isrc = _norm_isrc(raw.get("isrc"))
        suggested = by_isrc.get(isrc) if isrc else None
        if not suggested and title:
            suggested = by_title.get(title)
        out.append(serialize_unattached_snapshot(snap, suggested))
    return out


def attach_snapshot_to_work(db: Session, user: User, snapshot_id: str, work_id: str, *, admin: bool = False) -> dict:
    try:
        sid = uuid.UUID(snapshot_id)
        wid = uuid.UUID(work_id)
    except ValueError as exc:
        raise HTTPException(400, "Invalid id") from exc
    snap_q = db.query(PlatformMetricSnapshot).filter(PlatformMetricSnapshot.id == sid)
    if not admin:
        snap_q = snap_q.filter(PlatformMetricSnapshot.user_id == user.id)
    snap = snap_q.first()
    if not snap:
        raise HTTPException(404, "Snapshot not found")
    work_q = db.query(Work).filter(Work.id == wid)
    if not admin:
        work_q = work_q.filter(Work.owner_id == user.id)
    work = work_q.first()
    if not work:
        raise HTTPException(404, "Work not found")
    from app.services.royalty.settlement import prefer_label_release

    release = prefer_label_release(db, work.id)
    existing = (
        db.query(PlatformMetricSnapshot)
        .filter(
            PlatformMetricSnapshot.work_id == work.id,
            PlatformMetricSnapshot.channel_code == snap.channel_code,
            PlatformMetricSnapshot.period_key == snap.period_key,
            PlatformMetricSnapshot.source == snap.source,
            PlatformMetricSnapshot.id != snap.id,
        )
        .first()
    )
    if existing:
        existing.streams = (existing.streams or 0) + (snap.streams or 0)
        existing.saves = (existing.saves or 0) + (snap.saves or 0)
        existing.comments = (existing.comments or 0) + (snap.comments or 0)
        existing.revenue_minor = (existing.revenue_minor or 0) + (snap.revenue_minor or 0)
        match_kind = "isrc" if isrc_matches_work(db, work, release, (snap.raw or {}).get("isrc")) else "title"
        existing.usable_for_settlement = settlement_row_usable(
            source=existing.source, release=release, match_kind=match_kind
        )
        existing.release_id = release.id if release else existing.release_id
        merged = dict(existing.raw or {})
        merged["merged_from"] = str(snap.id)
        existing.raw = merged
        db.delete(snap)
        db.commit()
        drafts = (
            draft_settlements_for_periods(db, [existing.period_key])
            if existing.usable_for_settlement and existing.period_key
            else []
        )
        return {
            "attached": True,
            "merged": True,
            "snapshot_id": str(existing.id),
            "work_id": str(work.id),
            "usable_for_settlement": existing.usable_for_settlement,
            "match_kind": match_kind,
            "draft_batches": drafts,
        }
    snap.work_id = work.id
    snap.release_id = release.id if release else snap.release_id
    raw = dict(snap.raw or {})
    raw["attached_manually"] = True
    snap.raw = raw
    match_kind = "isrc" if isrc_matches_work(db, work, release, raw.get("isrc")) else "title"
    snap.usable_for_settlement = settlement_row_usable(source=snap.source, release=release, match_kind=match_kind)
    db.commit()
    drafts = (
        draft_settlements_for_periods(db, [snap.period_key])
        if snap.usable_for_settlement and snap.period_key
        else []
    )
    return {
        "attached": True,
        "merged": False,
        "snapshot_id": str(snap.id),
        "work_id": str(work.id),
        "usable_for_settlement": snap.usable_for_settlement,
        "match_kind": match_kind,
        "draft_batches": drafts,
    }


def attach_suggested_snapshots(db: Session, user: User) -> dict:
    rows = list_unattached_snapshots(db, user)
    attached = 0
    for row in rows:
        work_id = row.get("suggested_work_id")
        if not work_id:
            continue
        try:
            attach_snapshot_to_work(db, user, row["id"], work_id)
            attached += 1
        except HTTPException:
            continue
    return {"attached": attached, "checked": len(rows)}


def ingest_report(
    db: Session,
    *,
    user: User,
    content: bytes,
    filename: str,
    source: str,
    distributor_code: str | None = None,
    default_user_id: uuid.UUID | None = None,
) -> dict:
    if source not in SETTLEMENT_SOURCES | {"official_api", "licensed_analytics", "public_api"}:
        raise HTTPException(400, "Invalid report source")
    file_hash = hashlib.sha256(content).hexdigest()
    existing = db.query(RoyaltyReportImport).filter(RoyaltyReportImport.file_hash == file_hash).first()
    if existing and existing.status == "parsed":
        return {
            "import_id": str(existing.id),
            "row_count": existing.row_count,
            "deduped": True,
            "matched_works": 0,
            "unmatched_rows": 0,
            "periods": [],
            "usable_for_settlement": source in SETTLEMENT_SOURCES,
        }

    try:
        rows = parse_report_csv(content)
    except ValueError as exc:
        rec = RoyaltyReportImport(
            uploaded_by=user.id,
            source=source,
            distributor_code=distributor_code,
            filename=filename,
            file_hash=file_hash,
            status="failed",
            error_message=str(exc),
        )
        db.add(rec)
        db.commit()
        raise HTTPException(400, f"Could not parse report: {exc}") from exc

    key = None
    try:
        key, _ = get_storage_service().upload_bytes(
            content,
            f"reports/{user.id}/{file_hash[:12]}-{filename}",
            "text/csv",
        )
    except Exception:
        key = None

    rec = RoyaltyReportImport(
        uploaded_by=user.id,
        source=source,
        distributor_code=distributor_code,
        filename=filename,
        file_hash=file_hash,
        status="parsed",
        row_count=0,
        storage_key=key,
    )
    db.add(rec)
    db.flush()

    stored = 0
    matched_works = 0
    unmatched_rows = 0
    skipped_no_isrc = 0
    unmatched_titles: list[str] = []
    periods: set[str] = set()
    any_usable = False
    owner_hint = default_user_id or user.id
    for row in rows:
        if not row.get("channel_code"):
            continue
        work, release, match_kind = resolve_work_match(db, row, owner_hint)
        owner_id = work.owner_id if work else owner_hint
        periods.add(row["period_key"])
        if work:
            matched_works += 1
        else:
            unmatched_rows += 1
            title = (row.get("title") or row.get("isrc") or "").strip()
            if title and title not in unmatched_titles and len(unmatched_titles) < 8:
                unmatched_titles.append(title)
        usable = settlement_row_usable(source=source, release=release, match_kind=match_kind)
        if source in ISRC_REQUIRED_SOURCES and not usable:
            skipped_no_isrc += 1
        any_usable = any_usable or usable
        if upsert_metric_snapshot(
            db,
            user_id=owner_id,
            channel_code=row["channel_code"],
            period_key=row["period_key"],
            source=source,
            streams=row["streams"],
            saves=row["saves"],
            comments=row["comments"],
            revenue_minor=row["revenue_minor"],
            currency=row["currency"],
            work_id=work.id if work else None,
            release_id=release.id if release else None,
            distributor_code=distributor_code,
            raw={**row, "import_id": str(rec.id)},
            usable=usable,
        ):
            stored += 1
    rec.row_count = stored
    db.commit()
    rematch = rematch_unattached_snapshots(db, owner_hint)
    matched_works += int(rematch.get("matched") or 0)
    unmatched_rows = max(0, unmatched_rows - int(rematch.get("matched") or 0))
    drafts = draft_settlements_for_periods(db, periods) if any_usable and source in ISRC_REQUIRED_SOURCES else []
    persist_import_stats(
        rec,
        matched_works=matched_works,
        unmatched_rows=unmatched_rows,
        skipped_no_isrc=skipped_no_isrc,
        usable_for_settlement=any_usable,
        draft_batches=drafts,
    )
    db.commit()
    return {
        "import_id": str(rec.id),
        "row_count": stored,
        "deduped": False,
        "matched_works": matched_works,
        "unmatched_rows": unmatched_rows,
        "unmatched_titles": unmatched_titles,
        "rematched": rematch.get("matched") or 0,
        "periods": sorted(periods),
        "usable_for_settlement": any_usable,
        "skipped_no_isrc": skipped_no_isrc,
        "draft_batches": drafts,
    }


def draft_settlements_for_periods(db: Session, periods, *, isolate_auto_confirm: bool = False) -> list[dict]:
    from app.services.royalty.settlement import run_settlement

    out = []
    for key in sorted({str(item) for item in periods if item}):
        try:
            result = run_settlement(db, period_key=key, isolate_auto_confirm=isolate_auto_confirm)
        except Exception:
            continue
        out.append(
            {
                "period_key": result.get("period_key") or key,
                "batch_id": result.get("batch_id"),
                "lines": result.get("lines") or 0,
                "status": result.get("status"),
                "needs_confirm": result.get("needs_confirm"),
                "skipped": result.get("skipped") or {},
            }
        )
    return out


def revalidate_isrc_snapshots_for_work(db: Session, work_id) -> dict:
    work = db.query(Work).filter(Work.id == work_id).first()
    if not work:
        return {"checked": 0, "usable": 0, "rematched": 0, "draft_batches": []}
    rematch = rematch_unattached_snapshots(db, work.owner_id)
    from app.services.royalty.settlement import prefer_label_release

    release = prefer_label_release(db, work.id)
    rows = (
        db.query(PlatformMetricSnapshot)
        .filter(
            PlatformMetricSnapshot.work_id == work.id,
            PlatformMetricSnapshot.source.in_(tuple(ISRC_REQUIRED_SOURCES)),
            PlatformMetricSnapshot.settled.is_(False),
        )
        .all()
    )
    flipped = 0
    periods: set[str] = set()
    for snap in rows:
        match_kind = "isrc" if isrc_matches_work(db, work, release, (snap.raw or {}).get("isrc")) else "title"
        usable = settlement_row_usable(source=snap.source, release=release, match_kind=match_kind)
        if usable and not snap.usable_for_settlement:
            flipped += 1
        snap.usable_for_settlement = usable
        if usable and snap.period_key:
            periods.add(snap.period_key)
    db.commit()
    drafts = (
        draft_settlements_for_periods(db, periods)
        if periods and (flipped or rematch.get("matched"))
        else []
    )
    return {
        "checked": len(rows),
        "usable": flipped,
        "rematched": rematch.get("matched") or 0,
        "draft_batches": drafts,
    }


def list_isrc_unmatched_snapshots(db: Session, *, user_id=None, limit: int = 80) -> list[dict]:
    q = db.query(PlatformMetricSnapshot).filter(
        PlatformMetricSnapshot.source.in_(tuple(ISRC_REQUIRED_SOURCES)),
        PlatformMetricSnapshot.usable_for_settlement.is_(False),
        PlatformMetricSnapshot.settled.is_(False),
        PlatformMetricSnapshot.revenue_minor > 0,
    )
    if user_id:
        q = q.filter(PlatformMetricSnapshot.user_id == user_id)
    rows = (
        q.order_by(PlatformMetricSnapshot.created_at.desc())
        .limit(min(max(limit, 1), 200))
        .all()
    )
    work_ids = {row.work_id for row in rows if row.work_id}
    works = {w.id: w for w in db.query(Work).filter(Work.id.in_(work_ids)).all()} if work_ids else {}
    out = []
    for snap in rows:
        raw = dict(snap.raw or {})
        work = works.get(snap.work_id) if snap.work_id else None
        out.append(
            {
                **serialize_unattached_snapshot(snap, work),
                "work_id": str(snap.work_id) if snap.work_id else None,
                "work_title": work.title if work else None,
                "reason": "no_isrc" if not _norm_isrc(raw.get("isrc")) else "isrc_mismatch",
            }
        )
    return out


def persist_import_stats(row: RoyaltyReportImport, **stats) -> None:
    row.error_message = json.dumps({"_stats": True, **stats}, ensure_ascii=False, default=str)


def read_import_stats(row: RoyaltyReportImport) -> dict:
    raw = row.error_message or ""
    if not raw.startswith("{"):
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if data.get("_stats") else {}


def serialize_report_import(row: RoyaltyReportImport) -> dict:
    stats = read_import_stats(row)
    return {
        "id": str(row.id),
        "filename": row.filename,
        "source": row.source,
        "distributor_code": row.distributor_code,
        "status": row.status,
        "row_count": row.row_count or 0,
        "error_message": None if stats else row.error_message,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "usable_for_settlement": bool(stats.get("usable_for_settlement")),
        "skipped_no_isrc": int(stats.get("skipped_no_isrc") or 0),
        "matched_works": int(stats.get("matched_works") or 0),
        "unmatched_rows": int(stats.get("unmatched_rows") or 0),
        "draft_batches": stats.get("draft_batches") or [],
    }


def list_report_imports(db: Session, user: User | None = None, *, admin: bool = False, limit: int = 50) -> list[dict]:
    q = db.query(RoyaltyReportImport)
    if not admin:
        if user is None:
            return []
        q = q.filter(RoyaltyReportImport.uploaded_by == user.id)
    rows = q.order_by(RoyaltyReportImport.created_at.desc()).limit(min(max(limit, 1), 100)).all()
    return [serialize_report_import(row) for row in rows]


def ingest_partner_rows(
    db: Session,
    *,
    user: User,
    source: str,
    rows: list[dict],
    usable: bool,
) -> int:
    stored = 0
    for row in rows[:500]:
        channel = (row.get("channel_code") or row.get("store") or "").strip()
        period = (row.get("period_key") or datetime.utcnow().strftime("%Y-%m"))[:32]
        if not channel:
            continue
        work, release, match_kind = resolve_work_match(db, row, user.id)
        owner_id = work.owner_id if work else user.id
        upsert_metric_snapshot(
            db,
            user_id=owner_id,
            channel_code=channel,
            period_key=period,
            source=source,
            streams=int(row.get("streams") or 0),
            saves=int(row.get("saves") or 0),
            comments=int(row.get("comments") or 0),
            revenue_minor=int(row.get("revenue_minor") or 0),
            currency=(row.get("currency") or "USD").upper(),
            work_id=work.id if work else None,
            release_id=release.id if release else None,
            raw=row,
            usable=bool(usable and settlement_row_usable(source=source, release=release, match_kind=match_kind)),
        )
        stored += 1
    return stored


def fetch_licensed_analytics(db: Session) -> dict:
    from app.services.royalty.sync import sync_chartmetric_all

    return sync_chartmetric_all(db)


def fetch_youtube_analytics(db: Session) -> dict:
    from app.services.royalty.sync import sync_youtube_all

    return sync_youtube_all(db)
