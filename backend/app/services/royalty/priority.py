"""One work/channel/period settles once.

Official CSV (0.95) beats DOM harvest (0.75). A seated harvest that stamped
high confidence still beats official on family + rank.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

from app.services.distribution.catalog import HARVEST_SOURCES, OFFICIAL_SOURCES

HARVEST_MONEY = frozenset(HARVEST_SOURCES)
MONEY_SOURCES = frozenset(
    OFFICIAL_SOURCES
    | HARVEST_MONEY
    | {"user_export", "sync_license", "first_party_embed"}
)
SOURCE_RANK = {
    "seat_harvest": 50,
    "farm_harvest": 48,
    "user_connector": 46,
    "ops_connector": 40,
    "official_api": 30,
    "distributor_api": 28,
    "distributor_export": 26,
    "user_export": 20,
    "sync_license": 18,
    "first_party_radio": 16,
    "first_party_embed": 15,
}


def snapshot_conflict_key(snap) -> tuple:
    return (snap.user_id, snap.work_id, snap.channel_code, snap.period_key)


def official_covers(snap) -> bool:
    if snap.source not in OFFICIAL_SOURCES:
        return False
    return bool(getattr(snap, "usable_for_settlement", False) or (getattr(snap, "revenue_minor", 0) or 0) > 0)


def should_promote_connector(official_rows: Iterable) -> bool:
    return not any(official_covers(row) for row in official_rows)


def _source_family(source: str | None) -> int:
    if source in HARVEST_MONEY:
        return 2
    if source in OFFICIAL_SOURCES or source == "user_export":
        return 1
    return 0


def snapshot_confidence(snap) -> float:
    raw = getattr(snap, "raw", None) or {}
    if not isinstance(raw, dict):
        raw = {}
    explicit = raw.get("confidence")
    if explicit is not None:
        try:
            return float(explicit)
        except (TypeError, ValueError):
            pass
    source = getattr(snap, "source", None)
    if source in OFFICIAL_SOURCES or source == "user_export":
        return 0.95
    if source in HARVEST_MONEY:
        return 0.75
    return 0.0


def _winner(rows: list):
    pool = [row for row in rows if row.source in MONEY_SOURCES]
    if not pool:
        return None
    pool.sort(
        key=lambda row: (
            snapshot_confidence(row),
            _source_family(row.source),
            int(row.revenue_minor or 0),
            SOURCE_RANK.get(row.source, 0),
        ),
        reverse=True,
    )
    return pool[0]


def filter_settlement_snapshots(snaps: Iterable) -> list:
    grouped: dict[tuple, list] = defaultdict(list)
    for snap in snaps:
        if (snap.revenue_minor or 0) <= 0:
            continue
        if hasattr(snap, "usable_for_settlement") and not snap.usable_for_settlement:
            continue
        grouped[snapshot_conflict_key(snap)].append(snap)
    out = []
    for rows in grouped.values():
        chosen = _winner(rows)
        if chosen is not None:
            out.append(chosen)
    return out
