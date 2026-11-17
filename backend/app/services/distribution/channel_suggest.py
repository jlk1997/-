"""Advisory DSP channel picks from first-party listen / resonance / mood.

Never claims an official upload API. Suggestions do not auto-submit.
"""

from __future__ import annotations

from app.models.schemas import Work, WorkEngagementStats
from app.services.distribution.catalog import CHANNEL_NAMES

CN_FIRST = ["netease", "qq_music", "qishui"]
GLOBAL_FIRST = ["spotify", "youtube_music"]
# 国内店 → Spotify/YouTube → 短视频会话 → Apple
SHIP_COVERAGE_ORDER = [
    "netease",
    "qq_music",
    "kugou",
    "kuwo",
    "qishui",
    "bilibili",
    "spotify",
    "youtube_music",
    "douyin_musician",
    "kuaishou_musician",
    "wechat_channels",
    "apple_music",
]
CN_MOODS = {
    "calm",
    "night",
    "sleep",
    "lofi",
    "study",
    "rain",
    "healing",
    "sad",
    "nostalgia",
    "city",
    "chill",
    "ambient",
    "dream",
    "温暖",
    "治愈",
    "夜晚",
}
CN_GENRES = {"lofi", "c-pop", "mandopop", "healing", "folk", "rnb", "国风", "民谣"}
GLOBAL_MOODS = {"energetic", "party", "hype", "edm", "rock", "dance", "激昂"}


def _norm_set(values) -> set[str]:
    return {str(item).strip().lower() for item in (values or []) if str(item).strip()}


def resonance_avg(stats: WorkEngagementStats | None) -> float:
    if not stats:
        return 0.0
    count = int(stats.resonance_count or 0)
    if count <= 0:
        return 0.0
    return float(stats.resonance_total or 0) / count


def suggest_channels(
    work: Work | None,
    *,
    listen_completes: int = 0,
    resonance_avg: float = 0.0,
    listen_starts: int = 0,
    store_streams: dict | None = None,
) -> dict:
    moods = _norm_set(getattr(work, "moods", None) if work else None)
    genres = _norm_set(getattr(work, "genres", None) if work else None)
    starts = int(listen_starts or 0)
    completes = int(listen_completes or 0)
    complete_rate = (completes / starts) if starts >= 5 else None
    cn = 1
    global_score = 0
    if moods & CN_MOODS or genres & CN_GENRES:
        cn += 2
    if moods & GLOBAL_MOODS:
        global_score += 2
    if completes >= 8:
        cn += 1
    if float(resonance_avg or 0) >= 0.65:
        cn += 1
    if complete_rate is not None and complete_rate >= 0.55:
        cn += 2
    cn_store = 0
    global_store = 0
    for code, count in (store_streams or {}).items():
        try:
            n = int(count or 0)
        except (TypeError, ValueError):
            continue
        if code in {"netease", "qq_music", "qishui", "kugou", "kuwo", "douyin_musician", "kuaishou_musician", "wechat_channels", "bilibili"}:
            cn_store += n
        elif code in {"spotify", "apple_music", "youtube_music", "amazon_music", "deezer", "tiktok_music"}:
            global_store += n
    if cn_store > global_store * 1.2 and cn_store >= 200:
        cn += 2
    elif global_store > cn_store * 1.2 and global_store >= 200:
        global_score += 2
    if cn >= global_score:
        channels = list(CN_FIRST)
        region = "cn"
        reason_id = "cn_first"
        if complete_rate is not None:
            reason = f"完播 {int(round(complete_rate * 100))}%，建议先上网易+汽水"
        elif completes >= 8:
            reason = f"完播 {completes} 次，建议先上网易+汽水"
        else:
            reason = "国内情绪向作品，建议先上网易+汽水"
    else:
        channels = list(GLOBAL_FIRST)
        region = "global"
        reason_id = "global_first"
        reason = "节奏偏海外，建议先上 Spotify + YouTube Music"
    return {
        "advisory": True,
        "region": region,
        "reason_id": reason_id,
        "reason": reason,
        "channels": channels,
        "channel_names": [CHANNEL_NAMES.get(code, code) for code in channels],
        "also": list(GLOBAL_FIRST if region == "cn" else CN_FIRST[:2]),
        "listen_completes": completes,
        "resonance_avg": round(float(resonance_avg or 0), 3),
        "complete_rate": round(complete_rate, 3) if complete_rate is not None else None,
        "used_store_streams": bool(store_streams),
    }


def _qc_ok_for_ship(work) -> bool:
    pps = getattr(work, "post_process_status", None) or {}
    qc = pps.get("release_qc_result") if isinstance(pps, dict) else None
    if isinstance(qc, dict) and qc:
        return bool(qc.get("passed"))
    try:
        from app.services.work_quality import generation_preflight_from_work

        pre = generation_preflight_from_work(work)
        return bool(pre.get("duration_ok") and pre.get("loudness_ok"))
    except Exception:
        return True


def _seat_blocks(connection: dict | None) -> bool:
    if not connection:
        return False
    seat = connection.get("seat") or {}
    if seat.get("needs_challenge") or seat.get("status") in {"needs_challenge", "expired", "needs_session"}:
        return True
    if connection.get("status") == "needs_login" and connection.get("delivery_mode") == "session_assist":
        return True
    return False


def apply_suggested_ship(work, advisory: dict, *, connections: list[dict] | None = None) -> dict:
    """Keep only 1–3 stores that pass QC + SKU + live seat. Rest stay folded."""
    from app.services.distribution.asset_profiles import sku_gap_for_channel
    from app.services.distribution.catalog import channel_automation_level

    payload = dict(advisory or {})
    qc_ok = _qc_ok_for_ship(work) if work else False
    conn_by = {str(row.get("channel_code") or ""): row for row in (connections or [])}
    seen: set[str] = set()
    order: list[str] = []
    for code in list(payload.get("channels") or []) + SHIP_COVERAGE_ORDER:
        if code and code not in seen:
            seen.add(code)
            order.append(code)
    shippable: list[str] = []
    blocked: list[dict] = []
    for code in order:
        reason = None
        level = channel_automation_level(code)
        conn = conn_by.get(code) or {}
        paired = str(conn.get("status") or "") in {"settle", "metrics"}
        if level == "metrics_only" and not paired:
            reason = "metrics_seat"
        elif not qc_ok:
            reason = "qc"
        else:
            reason = sku_gap_for_channel(work, code)
        if not reason and _seat_blocks(conn_by.get(code)):
            reason = "seat"
        if reason:
            blocked.append({"code": code, "reason": reason})
            continue
        shippable.append(code)
        if len(shippable) >= 3:
            break
    payload["channels"] = shippable
    payload["shippable"] = shippable
    payload["channel_names"] = [CHANNEL_NAMES.get(code, code) for code in shippable]
    payload["blocked"] = blocked[:8]
    payload["also"] = [code for code in SHIP_COVERAGE_ORDER if code not in shippable][:8]
    payload["suggested_ship"] = True
    payload["qc_ok"] = qc_ok
    if shippable:
        if payload.get("region") == "global":
            payload["reason"] = payload.get("reason") or "这几家店质检、SKU 和席位都过了"
        else:
            payload["reason"] = payload.get("reason") or "这几家店质检、SKU 和席位都过了"
    else:
        payload["reason"] = "还没有店同时过质检、所需 SKU 和席位。先看四盏灯，其余店收在下面。"
    return payload


def suggest_channels_for_work(db, work: Work | None) -> dict:
    if not work or not getattr(work, "id", None):
        return suggest_channels(work)
    stats = db.query(WorkEngagementStats).filter(WorkEngagementStats.work_id == work.id).first()
    store_streams: dict[str, int] = {}
    try:
        from sqlalchemy import func
        from sqlalchemy.exc import OperationalError, ProgrammingError

        from app.models.schemas import PlatformMetricSnapshot

        rows = (
            db.query(PlatformMetricSnapshot.channel_code, func.coalesce(func.sum(PlatformMetricSnapshot.streams), 0))
            .filter(PlatformMetricSnapshot.work_id == work.id)
            .group_by(PlatformMetricSnapshot.channel_code)
            .all()
        )
        store_streams = {str(code): int(total or 0) for code, total in rows if code}
    except (OperationalError, ProgrammingError):
        store_streams = {}
    advisory = suggest_channels(
        work,
        listen_completes=int((stats.listen_completes if stats else 0) or 0),
        resonance_avg=resonance_avg(stats),
        store_streams=store_streams,
    )
    connections: list[dict] = []
    try:
        from app.models.schemas import User
        from app.services.seats.connections import build_connections
        from app.services.seats.service import list_seats

        owner = db.query(User).filter(User.id == work.owner_id).first() if getattr(work, "owner_id", None) else None
        if owner:
            seats = list_seats(db, owner)
            connections = build_connections(db, owner, seats)
    except Exception:
        connections = []
    return apply_suggested_ship(work, advisory, connections=connections)
