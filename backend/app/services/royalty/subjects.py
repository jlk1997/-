"""Fiat ledger subjects: in-house warmup vs inbound label royalties. Never mix with credits."""

from __future__ import annotations

from app.services.distribution.catalog import CONNECTOR_SOURCES, HARVEST_SOURCES, OFFICIAL_SOURCES

EXTERNAL_ROYALTY_SOURCES = frozenset(OFFICIAL_SOURCES | {"user_export"})
AUTO_CONFIRM_SOURCES = frozenset(
    {
        "seat_harvest",
        "farm_harvest",
        "sync_license",
        "first_party_embed",
    }
)
HARVEST_AUTO_CONFIRM_SOURCES = frozenset({"seat_harvest", "farm_harvest"})

SUBJECT_WARMUP = "warmup"
SUBJECT_LABEL = "label_royalty"
SUBJECT_SYNC = "sync"
SUBJECT_EMBED = "embed"
SUBJECT_CONNECTOR = "connector"
SUBJECT_HARVEST = "seat_harvest"
SUBJECT_WITHDRAWAL = "withdrawal"


def money_bucket(source: str | None) -> str:
    """radio / sync / embed / dsp / other. Harvest is the label money path."""
    src = (source or "").strip()
    if src == "first_party_radio":
        return "radio"
    if src == "sync_license":
        return "sync"
    if src == "first_party_embed":
        return "embed"
    if src in HARVEST_SOURCES or src in EXTERNAL_ROYALTY_SOURCES:
        return "dsp"
    return "other"


def accounting_subject(source: str | None, *, entry_type: str | None = None) -> str:
    if (entry_type or "").startswith("withdraw"):
        return SUBJECT_WITHDRAWAL
    src = (source or "").strip()
    if src == "first_party_radio":
        return SUBJECT_WARMUP
    if src == "first_party_embed":
        return SUBJECT_EMBED
    if src == "sync_license":
        return SUBJECT_SYNC
    if src in {"seat_harvest", "farm_harvest"}:
        return SUBJECT_HARVEST
    if src in CONNECTOR_SOURCES:
        return SUBJECT_HARVEST
    if src in EXTERNAL_ROYALTY_SOURCES or src in {"distributor_export", "distributor_api", "official_api"}:
        return SUBJECT_LABEL
    if src:
        return SUBJECT_HARVEST
    return SUBJECT_WARMUP


def subject_note_prefix(subject: str) -> str:
    return {
        SUBJECT_WARMUP: "电台预热",
        SUBJECT_LABEL: "厂牌版税",
        SUBJECT_SYNC: "同步授权",
        SUBJECT_EMBED: "嵌入完播",
        SUBJECT_CONNECTOR: "席位收割",
        SUBJECT_HARVEST: "席位收割",
        SUBJECT_WITHDRAWAL: "出金",
    }.get(subject, "法币")


def prefixed_ledger_note(note: str | None, *, source: str | None = None, entry_type: str | None = None) -> str:
    subject = accounting_subject(source, entry_type=entry_type)
    prefix = subject_note_prefix(subject)
    text = (note or "").strip()
    if not text:
        return prefix
    if text.startswith(prefix):
        return text
    return f"{prefix} · {text}"
