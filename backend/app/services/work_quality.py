"""Heuristic work quality scores for post-generation UX."""

from __future__ import annotations

from typing import Any

from app.models.schemas import ProvenanceRecord, Work


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def generation_preflight_from_work(work: Work) -> dict[str, Any]:
    pps = _as_dict(work.post_process_status)
    pre = _as_dict(pps.get("generation_preflight"))
    qc = _as_dict(pps.get("release_qc_result"))
    checks = _as_dict(qc.get("checks"))
    orig = _as_dict(qc.get("originality"))
    duration_ok = pre.get("duration_ok")
    if duration_ok is None:
        duration_ok = checks.get("duration_ok", True)
    loudness_ok = pre.get("loudness_ok")
    if loudness_ok is None:
        loudness_ok = checks.get("loudness_ok", True)
    has_cover = bool(work.cover_url or pre.get("has_cover") or checks.get("has_cover"))
    risk = int(orig.get("risk_score") or pre.get("originality_risk") or 0)
    return {
        "passed": bool(duration_ok and loudness_ok),
        "duration_ok": bool(duration_ok),
        "loudness_ok": bool(loudness_ok),
        "has_cover": has_cover,
        "originality_risk": risk,
        "duration": pre.get("duration") or work.duration,
        "lufs": pre.get("lufs"),
    }


def compute_work_quality(work: Work, prov: ProvenanceRecord | None = None) -> dict[str, Any]:
    moods = work.moods or []
    genres = work.genres or []
    pps = _as_dict(work.post_process_status)
    pre = generation_preflight_from_work(work)

    resonance = 72
    resonance += min(12, len(moods) * 3)
    resonance += min(6, len(genres) * 2)
    if work.cover_url:
        resonance += 4
    if work.arousal is not None and work.valence is not None:
        resonance += 3
    resonance = min(96, resonance)

    completion = 70
    if work.duration and work.duration >= 45:
        completion += 8
    elif work.duration:
        completion += 4
    if work.audio_url:
        completion += 6
    if pps.get("c2pa_done") or pps.get("c2pa") or work.cover_url:
        completion += 5
    if prov and (prov.music_request or prov.m3_request):
        completion += 4
    if not pre["loudness_ok"] or not pre["duration_ok"]:
        completion = min(completion, 54)
    completion = min(96, completion)

    if not pre["loudness_ok"]:
        suggestion_key = "loudness"
    elif not pre["duration_ok"]:
        suggestion_key = "duration"
    elif pre["originality_risk"] >= 80:
        suggestion_key = "originality"
    elif not pre["has_cover"]:
        suggestion_key = "cover"
    elif resonance < 80:
        suggestion_key = "mood"
    elif completion < 80:
        suggestion_key = "structure"
    else:
        suggestion_key = "publish"

    from app.services.distribution.asset_profiles import (
        clips_ready,
        instrumental_sku_ref,
        listing_master_ref,
        review_stems_ready,
        stems_quality,
    )

    listing = listing_master_ref(work)
    remelt = _as_dict(pps.get("remelt"))
    return {
        "resonance": resonance,
        "completion": completion,
        "suggestion_key": suggestion_key,
        "preflight": pre,
        "remelt_explain": remelt.get("explain"),
        "remelt_too_close": bool(remelt.get("too_close")),
        "remelt_distance": remelt.get("distance"),
        "reference_ready": bool(_as_dict(pps.get("reference")).get("embedding")),
        "release_assets": {
            "master_ready": bool(listing.get("wav_key")),
            "master_wav": bool(listing.get("wav_key")),
            "stems_quality": stems_quality(work) or "none",
            "evidence_ready": review_stems_ready(work),
            "sku_kind": pps.get("sku_kind"),
            "clips_needed": bool(getattr(work, "duration", None)),
            "clips_ready": clips_ready(work),
            "instrumental_ready": bool(instrumental_sku_ref(work).get("ready")),
        },
    }
