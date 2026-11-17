import uuid

from sqlalchemy.orm import Session

from app.models.schemas import ProvenanceRecord, Work

_MUSIC_PUBLIC_KEYS = (
    "prompt",
    "style_tags",
    "lyrics",
    "seed",
    "bpm",
    "key",
    "text_intent",
    "moods",
    "genres",
    "parent_work_id",
    "pack_id",
    "graph_hash",
    "exit",
    "not_store_multitrack",
    "intensity",
)


def _public_music_request(blob) -> dict | None:
    if not isinstance(blob, dict):
        return None
    return {key: blob[key] for key in _MUSIC_PUBLIC_KEYS if key in blob}


def _public_output(blob) -> dict | None:
    if not isinstance(blob, dict):
        return None
    return {
        "sha256": blob.get("sha256"),
        "human_edits": list(blob.get("human_edits") or []),
    }


def collect_human_edits(lineage: list[dict]) -> list[dict]:
    edits: list[dict] = []
    for item in lineage:
        for raw in item.get("human_edits") or []:
            if isinstance(raw, dict):
                edits.append(
                    {
                        "kind": raw.get("kind"),
                        "section": raw.get("section"),
                        "note": raw.get("note"),
                        "at": raw.get("at"),
                    }
                )
    return edits


def build_lineage(db: Session, work_id: uuid.UUID) -> list[dict]:
    lineage = []
    current_id = work_id
    visited = set()

    while current_id and current_id not in visited:
        visited.add(current_id)
        work = db.query(Work).filter(Work.id == current_id).first()
        if not work:
            break
        prov = db.query(ProvenanceRecord).filter(
            ProvenanceRecord.work_id == current_id
        ).first()

        entry = {
            "step": work.step_index or 0,
            "work_id": str(work.id),
            "type": prov.record_type if prov else "unknown",
            "title": work.title,
            "emotion": {
                "moods": work.moods or [],
                "genres": work.genres or [],
                "arousal": work.arousal,
                "valence": work.valence,
            },
            "parent_work_id": str(work.parent_work_id) if work.parent_work_id else None,
        }
        if prov:
            entry["music_request"] = _public_music_request(prov.music_request)
            entry["output"] = _public_output(prov.output_meta)
            entry["signature"] = prov.signature
            entry["pipeline_version"] = prov.pipeline_version
            entry["human_edits"] = list((prov.output_meta or {}).get("human_edits") or []) if isinstance(prov.output_meta, dict) else []

        lineage.append(entry)
        current_id = work.parent_work_id

    lineage.reverse()
    for i, item in enumerate(lineage):
        item["step"] = i
    return sanitize_lineage_for_client(lineage)


_VENDOR_LEAK_KEYS = frozenset(
    {
        "vendor",
        "vendor_id",
        "vendor_key_prefix",
        "model",
        "m3_request",
        "task_id",
        "api_key",
        "base_url",
    }
)


def sanitize_lineage_for_client(lineage: list[dict]) -> list[dict]:
    """Drop vendor identity and internal request blobs before they reach the mini program."""
    return [_sanitize_node(item) for item in lineage]


def _sanitize_node(value):
    if isinstance(value, dict):
        return {key: _sanitize_node(item) for key, item in value.items() if key not in _VENDOR_LEAK_KEYS}
    if isinstance(value, list):
        return [_sanitize_node(item) for item in value]
    return value
