"""Display-only DSP revenue ranges. Never writes settlement revenue_minor."""

from __future__ import annotations

from sqlalchemy.orm import Session

# Per-stream ranges in minor units of the channel's default currency.
# Low/high are conservative bands, not a statement. Geo mix can stretch them.
_RATE: dict[str, tuple[str, int, int]] = {
    "spotify": ("USD", 2, 6),
    "apple_music": ("USD", 6, 12),
    "youtube_music": ("USD", 1, 4),
    "amazon_music": ("USD", 3, 8),
    "deezer": ("USD", 3, 7),
    "tiktok_music": ("USD", 1, 4),
    "soundcloud": ("USD", 1, 3),
    "bandcamp": ("USD", 8, 20),
    "netease": ("CNY", 1, 4),
    "qq_music": ("CNY", 1, 4),
    "kugou": ("CNY", 1, 3),
    "kuwo": ("CNY", 1, 3),
    "qishui": ("CNY", 1, 3),
    "bilibili": ("CNY", 1, 4),
    "douyin_musician": ("CNY", 1, 3),
    "kuaishou_musician": ("CNY", 1, 3),
    "wechat_channels": ("CNY", 1, 3),
}

_GEO_STRETCH = {
    "US": 1.25,
    "GB": 1.15,
    "DE": 1.1,
    "JP": 1.05,
    "CN": 0.85,
    "IN": 0.55,
    "BR": 0.7,
    "OTHER": 0.9,
}


def _band(channel_code: str | None) -> tuple[str, int, int]:
    return _RATE.get((channel_code or "").strip(), ("CNY", 1, 3))


def normalize_geo(raw) -> dict[str, float] | None:
    """Turn overlay/CSV geo blobs into {CC: weight}. None if empty."""
    if not raw:
        return None
    if isinstance(raw, str):
        code = raw.strip().upper()
        return {code: 1.0} if code else None
    if isinstance(raw, dict):
        if any(key in raw for key in ("countries", "mix", "geo")):
            nested = None
            for key in ("countries", "mix", "geo"):
                if key in raw:
                    nested = normalize_geo(raw.get(key))
                    if nested:
                        break
            if nested:
                return nested
        out: dict[str, float] = {}
        for key, value in raw.items():
            code = str(key or "").strip().upper()
            if not code or code in {"UNKNOWN", "NONE", "NULL", "COUNTRIES", "MIX", "GEO"}:
                continue
            try:
                if isinstance(value, dict):
                    count = float(value.get("streams") or value.get("count") or value.get("share") or 0)
                else:
                    count = float(value)
            except (TypeError, ValueError):
                continue
            if count > 0:
                out[code] = out.get(code, 0.0) + count
        return out or None
    if isinstance(raw, list):
        out = {}
        for item in raw:
            if isinstance(item, str):
                code = item.strip().upper()
                if code:
                    out[code] = out.get(code, 0.0) + 1.0
            elif isinstance(item, dict):
                code = str(item.get("country") or item.get("code") or item.get("geo") or "").strip().upper()
                try:
                    count = float(item.get("streams") or item.get("count") or item.get("share") or 1)
                except (TypeError, ValueError):
                    count = 1.0
                if code and count > 0:
                    out[code] = out.get(code, 0.0) + count
        return out or None
    return None


def _geo_factor(geo: dict | None) -> float:
    mix = normalize_geo(geo)
    if not mix:
        return 1.0
    total = 0.0
    weight = 0.0
    for code, streams in mix.items():
        try:
            count = float(streams)
        except (TypeError, ValueError):
            continue
        if count <= 0:
            continue
        stretch = _GEO_STRETCH.get(str(code).upper(), _GEO_STRETCH["OTHER"])
        total += count * stretch
        weight += count
    if weight <= 0:
        return 1.0
    return max(0.5, min(1.4, total / weight))


def historical_rate(
    db: Session | None,
    *,
    user_id=None,
    channel_code: str | None = None,
) -> float | None:
    """Minor-per-stream from this user's booked harvest rows. None if too thin."""
    if db is None or user_id is None or not channel_code:
        return None
    from sqlalchemy import func
    from sqlalchemy.exc import OperationalError, ProgrammingError

    from app.models.schemas import PlatformMetricSnapshot

    try:
        row = (
            db.query(
                func.coalesce(func.sum(PlatformMetricSnapshot.revenue_minor), 0),
                func.coalesce(func.sum(PlatformMetricSnapshot.streams), 0),
                func.count(PlatformMetricSnapshot.id),
            )
            .filter(
                PlatformMetricSnapshot.user_id == user_id,
                PlatformMetricSnapshot.channel_code == channel_code,
                PlatformMetricSnapshot.usable_for_settlement.is_(True),
                PlatformMetricSnapshot.revenue_minor > 0,
                PlatformMetricSnapshot.streams > 0,
            )
            .first()
        )
    except (OperationalError, ProgrammingError):
        return None
    if not row:
        return None
    revenue, streams, n = int(row[0] or 0), int(row[1] or 0), int(row[2] or 0)
    if n < 2 or streams <= 0 or revenue <= 0:
        return None
    return revenue / streams


def owner_share(db: Session | None, work_id, user_id) -> float:
    if db is None or not work_id or not user_id:
        return 1.0
    import uuid as uuid_lib

    from app.models.schemas import Work
    from app.services.royalty.splits import _raw_shares

    wid = work_id
    uid = user_id
    try:
        if isinstance(work_id, str):
            wid = uuid_lib.UUID(work_id)
        if isinstance(user_id, str):
            uid = uuid_lib.UUID(user_id)
    except (TypeError, ValueError):
        return 1.0
    work = db.query(Work).filter(Work.id == wid).first()
    if not work:
        return 1.0
    shares = _raw_shares(db, work)
    for row in shares:
        if str(row.get("user_id") or "") == str(uid):
            return max(0.0, min(1.0, float(row.get("percent") or 0) / 100.0))
    if str(work.owner_id) == str(uid):
        return 1.0
    return 1.0


def predict_revenue(
    channel_code: str | None,
    streams: int,
    *,
    currency: str | None = None,
    geo: dict | None = None,
    share: float = 1.0,
    history_rate: float | None = None,
) -> dict:
    """Interval estimate from streams. Not settlement-grade."""
    count = max(0, int(streams or 0))
    cur, low_rate, high_rate = _band(channel_code)
    if currency:
        cur = str(currency).upper()
    mix = normalize_geo(geo)
    geo_only = _geo_factor(mix)
    factor = geo_only * max(0.0, min(1.0, float(share or 1.0)))
    basis = "catalog"
    if history_rate and history_rate > 0 and count > 0:
        mid = int(round(count * float(history_rate) * factor))
        spread = max(1, int(round(mid * 0.3)))
        low = max(0, mid - spread)
        high = mid + spread
        basis = "history"
    else:
        low = int(round(count * low_rate * factor))
        high = int(round(count * high_rate * factor))
        if high < low:
            high = low
        mid = int(round((low + high) / 2))
    confidence = 0.0
    if count >= 10000:
        confidence = 0.82 if mix else 0.68
    elif count >= 1000:
        confidence = 0.7 if mix else 0.55
    elif count > 0:
        confidence = 0.45 if mix else 0.32
    if basis == "history":
        confidence = min(0.92, confidence + 0.12)
    if share < 1:
        confidence = max(0.2, confidence - 0.05)
    return {
        "low_minor": low,
        "mid_minor": mid,
        "high_minor": high,
        "currency": cur,
        "confidence": confidence,
        "streams": count,
        "share": round(float(share or 1.0), 4),
        "basis": basis,
        "geo_applied": bool(mix),
        "geo_factor": round(geo_only, 3),
        "disclaimer": "estimated_not_settlement",
    }


def _merge_geo(into: dict[str, float], geo: dict[str, float] | None) -> None:
    if not geo:
        return
    for code, count in geo.items():
        into[code] = into.get(code, 0.0) + float(count)


def load_geo_index(db: Session | None, user_id) -> dict:
    """One query of snapshot geo, keyed for hub attach loops."""
    empty: dict = {"channel": {}, "work": {}, "both": {}, "user": None}
    if db is None or user_id is None:
        return empty
    from sqlalchemy.exc import OperationalError, ProgrammingError

    from app.models.schemas import PlatformMetricSnapshot

    uid = user_id
    try:
        import uuid as uuid_lib

        if isinstance(user_id, str):
            uid = uuid_lib.UUID(user_id)
    except (TypeError, ValueError):
        return empty
    try:
        rows = (
            db.query(
                PlatformMetricSnapshot.channel_code,
                PlatformMetricSnapshot.work_id,
                PlatformMetricSnapshot.raw,
                PlatformMetricSnapshot.streams,
            )
            .filter(PlatformMetricSnapshot.user_id == uid)
            .all()
        )
    except (OperationalError, ProgrammingError):
        return empty
    by_channel: dict[str, dict[str, float]] = {}
    by_work: dict[str, dict[str, float]] = {}
    by_both: dict[tuple[str, str], dict[str, float]] = {}
    by_user: dict[str, float] = {}
    for channel, work_id, raw, streams in rows:
        mix = normalize_geo((raw or {}).get("geo") or (raw or {}).get("countries"))
        if not mix:
            continue
        total = sum(mix.values())
        if total <= 1.01 and all(v <= 1.0 for v in mix.values()) and int(streams or 0) > 0:
            mix = {code: weight * float(streams) for code, weight in mix.items()}
        code = str(channel or "").strip()
        wid = str(work_id) if work_id else None
        if code:
            _merge_geo(by_channel.setdefault(code, {}), mix)
        if wid:
            _merge_geo(by_work.setdefault(wid, {}), mix)
        if code and wid:
            _merge_geo(by_both.setdefault((code, wid), {}), mix)
        _merge_geo(by_user, mix)
    return {"channel": by_channel, "work": by_work, "both": by_both, "user": by_user or None}


def geo_from_index(index: dict | None, *, channel_code: str | None = None, work_id=None) -> dict | None:
    if not index:
        return None
    cid = (channel_code or "").strip() or None
    wid = str(work_id) if work_id else None
    both = index.get("both") or {}
    channel = index.get("channel") or {}
    work = index.get("work") or {}
    if cid and wid:
        return both.get((cid, wid)) or work.get(wid) or channel.get(cid)
    if cid:
        return channel.get(cid)
    if wid:
        return work.get(wid)
    return index.get("user")


def geo_mix(db: Session | None, *, user_id=None, channel_code: str | None = None, work_id=None) -> dict | None:
    return geo_from_index(load_geo_index(db, user_id), channel_code=channel_code, work_id=work_id)


def merge_predictions(preds: list[dict] | None) -> dict | None:
    """Sum per-store ranges. Never convert currencies; pick the largest bucket as the headline."""
    rows = [row for row in (preds or []) if isinstance(row, dict)]
    if not rows:
        return None
    by_cur: dict[str, dict] = {}
    history = 0
    geo = False
    for pred in rows:
        cur = str(pred.get("currency") or "CNY").upper()
        bucket = by_cur.setdefault(
            cur,
            {"low_minor": 0, "mid_minor": 0, "high_minor": 0, "streams": 0, "n": 0},
        )
        bucket["low_minor"] += int(pred.get("low_minor") or 0)
        bucket["mid_minor"] += int(pred.get("mid_minor") or 0)
        bucket["high_minor"] += int(pred.get("high_minor") or 0)
        bucket["streams"] += int(pred.get("streams") or 0)
        bucket["n"] += 1
        if pred.get("basis") == "history":
            history += 1
        if pred.get("geo_applied"):
            geo = True
    if not by_cur:
        return None
    ranked = sorted(by_cur.items(), key=lambda item: item[1]["mid_minor"], reverse=True)
    currency, top = ranked[0]
    return {
        "low_minor": top["low_minor"],
        "mid_minor": top["mid_minor"],
        "high_minor": top["high_minor"],
        "currency": currency,
        "streams": sum(item["streams"] for item in by_cur.values()),
        "basis": "history" if history else "catalog",
        "geo_applied": geo,
        "disclaimer": "estimated_not_settlement",
        "by_currency": [
            {"currency": code, **bucket} for code, bucket in ranked
        ],
        "calibrated": any(bool(row.get("calibrated")) for row in rows),
    }


def calibration_factor(db: Session | None, *, user_id=None, channel_code: str | None = None) -> float | None:
    """Actual booked / last catalog mid. None if too thin. Never writes settlement."""
    if db is None or user_id is None or not channel_code:
        return None
    from sqlalchemy.exc import OperationalError, ProgrammingError

    from app.models.schemas import PlatformMetricSnapshot

    try:
        rows = (
            db.query(PlatformMetricSnapshot.revenue_minor, PlatformMetricSnapshot.raw)
            .filter(
                PlatformMetricSnapshot.user_id == user_id,
                PlatformMetricSnapshot.channel_code == channel_code,
                PlatformMetricSnapshot.usable_for_settlement.is_(True),
                PlatformMetricSnapshot.revenue_minor > 0,
            )
            .limit(40)
            .all()
        )
    except (OperationalError, ProgrammingError):
        return None
    predicted = 0
    actual = 0
    n = 0
    for revenue, raw in rows:
        pred = (raw or {}).get("prediction") if isinstance(raw, dict) else None
        mid = int((pred or {}).get("mid_minor") or 0)
        booked = int(revenue or 0)
        if mid <= 0 or booked <= 0:
            continue
        predicted += mid
        actual += booked
        n += 1
    if n < 2 or predicted <= 0:
        return None
    return max(0.4, min(2.5, actual / predicted))


def attach_prediction(
    target: dict,
    channel_code: str | None,
    streams: int,
    *,
    currency: str | None = None,
    geo: dict | None = None,
    geo_index: dict | None = None,
    db: Session | None = None,
    user_id=None,
    work_id=None,
) -> dict:
    share = owner_share(db, work_id, user_id) if work_id else 1.0
    history = historical_rate(db, user_id=user_id, channel_code=channel_code)
    if geo is None:
        if geo_index is not None:
            geo = geo_from_index(geo_index, channel_code=channel_code, work_id=work_id)
        elif db is not None and user_id is not None:
            geo = geo_mix(db, user_id=user_id, channel_code=channel_code, work_id=work_id)
    pred = predict_revenue(
        channel_code,
        streams,
        currency=currency,
        geo=geo,
        share=share,
        history_rate=history,
    )
    factor = calibration_factor(db, user_id=user_id, channel_code=channel_code)
    if factor and pred.get("basis") == "catalog":
        for key in ("low_minor", "mid_minor", "high_minor"):
            pred[key] = int(round(int(pred.get(key) or 0) * factor))
        pred["calibrated"] = True
        pred["calibration_factor"] = round(factor, 3)
    target["predicted_revenue"] = pred
    return pred


def store_compare(channels: list[dict]) -> dict | None:
    """One-line cross-store hint from synced plays / predicted mid. Display only."""
    ranked = []
    for row in channels or []:
        pred = row.get("predicted_revenue") or {}
        streams = int(row.get("display_streams") or 0) + int(row.get("streams") or 0)
        ranked.append(
            {
                "channel_code": row.get("channel_code"),
                "streams": streams,
                "mid_minor": int(pred.get("mid_minor") or 0),
                "has_real": bool(row.get("has_real")),
            }
        )
    ranked = [row for row in ranked if row["channel_code"] and row["streams"] > 0]
    if len(ranked) < 2:
        return None
    ranked.sort(key=lambda row: (row["streams"], row["mid_minor"]), reverse=True)
    top, runner = ranked[0], ranked[1]
    return {
        "reason_id": "sync_lead",
        "top_channel": top["channel_code"],
        "runner_up": runner["channel_code"],
        "top_streams": top["streams"],
        "top_predicted_mid_minor": top["mid_minor"],
        "top_booked": top["has_real"],
    }
