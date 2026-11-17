from __future__ import annotations

import csv
import io
import json
import zipfile

from app.models.schemas import Release, ReleaseMetadata, Work
from app.services.distribution.asset_profiles import (
    aggregate_needs,
    profile_for,
    release_asset_status,
    review_stems_ready,
)
from app.services.distribution.catalog import (
    channel_display_name,
    channel_sop,
    channel_upload_url,
    clip_windows,
    list_portal_channels,
)
from app.services.media import cut_audio_clip, probe_audio, transcode_audio
from app.services.stem_assets import MISSING_REVIEW_STEMS_NOTE as MISSING_REVIEW_NOTE
from app.services.stem_assets import load_review_stem_bytes, provenance_payload, write_originality_into_kit
from app.services.storage import get_storage_service


def build_self_release_kit(
    *,
    work: Work,
    release: Release,
    meta: ReleaseMetadata | None,
    audio_bytes: bytes | None,
    db=None,
) -> dict:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        csv_buf = io.StringIO()
        writer = csv.writer(csv_buf)
        from app.services.distribution.channel_fields import LISTING_KEYS, listing_from_metadata, metadata_value

        cover_url = (meta.cover_url if meta else None) or (work.cover_url or "")
        listing = listing_from_metadata(meta)
        header = [
            "title",
            "artist",
            "isrc",
            "upc",
            "cover_url",
            "genres",
            "language",
            "ai_disclosed",
            "channels",
            "lyrics_file",
            *LISTING_KEYS,
        ]
        writer.writerow(header)
        writer.writerow([
            (meta.title if meta else work.title),
            (meta.artist_name if meta else "") or "",
            (meta.isrc if meta else work.isrc) or "",
            (meta.upc if meta else "") or "",
            cover_url or "",
            ",".join((meta.genres if meta else work.genres) or []),
            (meta.language if meta else "zh") or "zh",
            "yes" if (meta.ai_disclosed if meta else False) else "no",
            ",".join(release.selected_channels or []),
            "lyrics.txt",
            *[
                ""
                if metadata_value(meta, key) is None
                else (
                    "yes"
                    if metadata_value(meta, key) is True
                    else "no"
                    if metadata_value(meta, key) is False
                    else ",".join(str(item) for item in metadata_value(meta, key))
                    if isinstance(metadata_value(meta, key), list)
                    else str(metadata_value(meta, key))
                )
                for key in LISTING_KEYS
            ],
        ])
        zf.writestr("metadata.csv", csv_buf.getvalue())
        from app.services.distribution.channel_fields import handoff_lines

        sheet = handoff_lines(meta, list(release.selected_channels or []))
        zf.writestr(
            "handoff.txt",
            "\n".join(f"{row['label']}: {row['value'] or '（空）'}" for row in sheet) or "（没有发行资料）",
        )
        credit_lines = [
            f"作词: {listing.get('lyricist') or ''}",
            f"作曲: {listing.get('composer') or ''}",
            f"编曲: {listing.get('arranger') or ''}",
            f"制作: {listing.get('producer') or ''}",
            f"合作艺人: {listing.get('featured_artists') or ''}",
            f"厂牌: {listing.get('label_name') or ''}",
            f"词曲版权: {listing.get('copyright_line') or ''}",
            f"录音版权: {listing.get('sound_recording_line') or ''}",
            f"内容分级: {listing.get('explicit') or ''}",
            f"发行日期: {listing.get('release_date') or ''}",
        ]
        zf.writestr("credits.txt", "\n".join(credit_lines) + "\n")
        from app.core.lyrics_structure import strip_structure_tags

        lyrics_text = strip_structure_tags((meta.lyrics if meta and meta.lyrics else "") or "")
        if not lyrics_text and listing.get("instrumental") is True:
            lyrics_text = "纯音乐"
        zf.writestr("lyrics.txt", lyrics_text if lyrics_text.endswith("\n") or not lyrics_text else lyrics_text + "\n")
        channels = release.selected_channels or []
        portals = list_portal_channels()
        duration = getattr(work, "duration", None)
        if audio_bytes and not duration:
            duration = (probe_audio(audio_bytes) or {}).get("duration")
        clips = clip_windows(duration)
        checklist = "\n".join(
            f"- [ ] {channel_display_name(code)} ({code})\n    {channel_sop(code)}\n    portal: {channel_upload_url(code) or '-'}"
            for code in channels
        ) or "- [ ] (no channels selected)"
        portal_lines = "\n".join(
            f"- [ ] {item['name']} ({item['code']})\n    {item['sop']}\n    portal: {item['upload_url']}"
            for item in portals
        )
        clip_lines = "\n".join(f"- {item['length']}s @ {item['start']}-{item['end']}" for item in clips) or "- (track too short)"
        mode = release.mode or "label"
        needs = aggregate_needs(channels)
        asset_status = release_asset_status(work, channels)
        evidence_ready = review_stems_ready(work)
        originality_note = (
            "originality/ 为国内音乐人原创证明（Demucs 隔离轨 + 伴奏 + 生成记录）。禁止把 vocal/drums 当成多首歌上架。"
            if evidence_ready and needs["needs_stems_evidence"]
            else (
                f"{MISSING_REVIEW_NOTE}\n"
                if needs["needs_stems_evidence"]
                else "全球 DSP 只上架一条立体声母带，本包不含分轨。"
            )
        )
        zf.writestr(
            "README.txt",
            (
                "Vibe Sorcery 发行资产包 / release kit\n"
                f"mode: {mode}\n\n"
                "资产分工（不要混成一条上传通路）:\n"
                "- 正片上架：audio/master.wav（一条 44.1kHz 16-bit 立体声母带）。DistroKid / TuneCore / Spotify 不要把人声和鼓轨当分曲上传。\n"
                "- TuneCore 推荐 24-bit：若有 audio/master_24bit.wav，优先传它；16-bit 母带仍被接受。\n"
                "- 原创证明：仅国内音乐人电音/入驻/被拒补件。审核级分轨只在 originality/，且必须是 Demucs。\n"
                "- 短视频：audio/clips/ 的 15s/30s 高潮切片。汽水完整曲仍用母带。\n"
                "- 伴奏商品：独立曲目发行，不要和证明包混用。\n"
                f"{originality_note}\n\n"
                "渠道作战手册 / Channel SOP:\n"
                f"{checklist}\n\n"
                "缺席渠道门户 / extra portals (deep link + receipt only):\n"
                f"{portal_lines}\n\n"
                "短视频切片窗口 / short-video clip windows:\n"
                f"{clip_lines}\n"
                "切片文件在 audio/clips/，请用创作者自己的账号发布后再把链接贴回。\n\n"
                "个人代发：用你自己的创作者后台上传本包，回到创作者中心粘贴商店链接。数据只展示，不参与分成。\n"
                "Self-release: upload this kit in your own store console, then paste store URLs. Display-only.\n"
                "厂牌模式：由平台账号代发，请不要自己上传。\n"
                "Label mode: ops delivers via the platform account. Do not upload this kit yourself.\n"
                "平台不会保存第三方密码，也不会登录不受控的账号。\n"
            ),
        )
        cover_bytes = _cover_bytes(work, meta)
        if cover_bytes:
            zf.writestr("artwork/cover.jpg", cover_bytes)
        zf.writestr("channels.txt", "\n".join(f"{channel_display_name(code)}\t{code}" for code in channels))
        for code in channels:
            profile = profile_for(code)
            listing_file = "audio/master.wav" if profile.needs_master else "n/a"
            evidence = "originality/ (Demucs only — not the listing file)" if profile.needs_stems_evidence else "none"
            clips_line = "audio/clips/" if profile.needs_clips else "none"
            inst = "release a separate instrumental SKU" if profile.needs_instrumental else "no"
            zf.writestr(
                f"channels/{code}/README.txt",
                (
                    f"{channel_display_name(code)} ({code})\n"
                    f"listing: {listing_file}\n"
                    f"evidence: {evidence}\n"
                    f"clips: {clips_line}\n"
                    f"instrumental: {inst}\n\n"
                    f"{channel_sop(code)}\n"
                ),
            )
        originality_files: list[str] = []
        stem_bytes: dict[str, bytes] = {}
        has_24bit = False
        if audio_bytes:
            wav = None
            mp3 = None
            try:
                wav = transcode_audio(audio_bytes, fmt="wav")
            except Exception:
                wav = None
            try:
                mp3 = transcode_audio(audio_bytes, fmt="mp3", bitrate="320k")
            except Exception:
                mp3 = None
            wav24 = None
            if wav or mp3:
                from app.models.schemas import ProvenanceRecord
                from app.services.media import stamp_aigc_mark

                prov = None
                if db is not None:
                    prov = (
                        db.query(ProvenanceRecord)
                        .filter(ProvenanceRecord.work_id == work.id)
                        .order_by(ProvenanceRecord.created_at.desc())
                        .first()
                    )
                request = prov.music_request if prov and isinstance(prov.music_request, dict) else {}
                model_name = str(request.get("model") or "")
                trace = str(request.get("trace_id") or "")
                if wav:
                    wav = stamp_aigc_mark(wav, model=model_name, trace_id=trace, fmt="wav")
                if mp3:
                    mp3 = stamp_aigc_mark(mp3, model=model_name, trace_id=trace, fmt="mp3")
            if wav:
                zf.writestr("audio/master.wav", wav)
                if any(profile_for(code).group == "dsp_global" for code in channels):
                    try:
                        wav24 = transcode_audio(audio_bytes, fmt="wav", bit_depth=24)
                    except Exception:
                        wav24 = None
                    if wav24:
                        zf.writestr("audio/master_24bit.wav", wav24)
                        has_24bit = True
            if mp3:
                zf.writestr("audio/master_320.mp3", mp3)
            if not wav and not mp3:
                zf.writestr("audio/source.bin", audio_bytes)
            written_clips = _write_clip_files(zf, audio_bytes, clips, folder="audio/clips")
            if written_clips:
                clips[:] = written_clips
        if evidence_ready:
            stem_bytes = load_review_stem_bytes(work)
        if needs["needs_stems_evidence"] and stem_bytes:
            originality_files = write_originality_into_kit(
                zf,
                stem_bytes=stem_bytes,
                provenance=provenance_payload(db, work),
                include_instrumental=True,
            )
        if needs["needs_clips"] and stem_bytes.get("accompaniment"):
            extra = _write_accompaniment_clip(zf, stem_bytes["accompaniment"], clips)
            if extra:
                clips.append(extra)
        zf.writestr(
            "ops_checklist.json",
            json.dumps(
                {
                    "mode": mode,
                    "release_id": str(release.id),
                    "work_id": str(work.id),
                    "title": (meta.title if meta else work.title),
                    "artist_name": (meta.artist_name if meta else "") or "",
                    "isrc": (meta.isrc if meta else work.isrc) or "",
                    "upc": (meta.upc if meta else "") or "",
                    "cover_url": (meta.cover_url if meta else None) or (work.cover_url or ""),
                    "channels": channels,
                    "sops": {code: channel_sop(code) for code in channels},
                    "portal_channels": portals,
                    "clip_windows": clips,
                    "asset_status": asset_status,
                    "originality_files": originality_files,
                    "listing_asset": "audio/master.wav",
                    "listing": listing,
                    "tunecore_preferred": "audio/master_24bit.wav" if has_24bit else None,
                    "label_instruction": "Deliver from the platform-owned store console. Do not use end-user passwords.",
                    "self_release_instruction": "User uploads this kit from their own console. Display-only analytics.",
                    "partner_tracks": "master_only",
                    "channel_folders": [f"channels/{code}/README.txt" for code in channels],
                },
                ensure_ascii=False,
                indent=2,
            ),
        )

    data = buf.getvalue()
    key, url = get_storage_service().upload_bytes(
        data,
        f"releases/{release.id}/self-release-kit.zip",
        "application/zip",
    )
    return {"key": key, "url": url, "bytes": len(data), "asset_status": asset_status}


def _write_clip_files(zf: zipfile.ZipFile, audio_bytes: bytes, clips: list[dict], *, folder: str) -> list[dict]:
    written: list[dict] = []
    for window in clips:
        try:
            clip = cut_audio_clip(
                audio_bytes,
                start=float(window.get("start") or 0),
                duration=float(window.get("length") or 0),
            )
        except Exception:
            clip = None
        if not clip:
            continue
        name = f"{folder}/clip_{int(window.get('length') or 0)}s.mp3"
        zf.writestr(name, clip)
        written.append({**window, "file": name})
    if written:
        zf.writestr(
            f"{folder}/README.txt",
            (
                "15s/30s climax clips for short-video BGM. Upload from your own account, then paste the URL back.\n"
                "accompaniment_32s.mp3 is optional instrumental BGM when Demucs accompaniment exists — not a DSP track.\n"
            ),
        )
    return written


def _write_accompaniment_clip(zf: zipfile.ZipFile, accomp_bytes: bytes, clips: list[dict]) -> dict | None:
    start = float(clips[0].get("start") or 0) if clips else 0.0
    try:
        clip = cut_audio_clip(accomp_bytes, start=start, duration=32.0)
    except Exception:
        clip = None
    if not clip:
        return None
    name = "audio/clips/accompaniment_32s.mp3"
    zf.writestr(name, clip)
    return {"length": 32, "start": round(start, 2), "file": name, "use": "short_video_instrumental"}


def build_clip_pack(*, work: Work, audio_bytes: bytes | None) -> dict:
    """Standalone 15s/30s climax pack — no full kit, no fake DSP upload."""
    duration = getattr(work, "duration", None)
    if audio_bytes and not duration:
        duration = (probe_audio(audio_bytes) or {}).get("duration")
    clips = clip_windows(duration)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        written = _write_clip_files(zf, audio_bytes, clips, folder="clips") if audio_bytes else []
        windows = written or clips
        zf.writestr(
            "README.txt",
            (
                "Vibe Sorcery 短视频切片包 / clip pack\n"
                f"work: {getattr(work, 'title', '') or getattr(work, 'id', '')}\n\n"
                "用自己的账号把 clips/ 里的 15s/30s 高潮切片发到短视频平台，再把链接贴回作品账本。\n"
                "Post these climax clips from your own account, then paste the URL back. Display-only.\n"
                "平台不会登录第三方账号，也不会替你上传。\n"
            ),
        )
        zf.writestr(
            "clip_windows.json",
            json.dumps({"work_id": str(getattr(work, "id", "") or ""), "clip_windows": windows}, ensure_ascii=False, indent=2),
        )
    data = buf.getvalue()
    key, url = get_storage_service().upload_bytes(
        data,
        f"works/{getattr(work, 'id', 'work')}/clip-pack.zip",
        "application/zip",
    )
    return {"key": key, "url": url, "bytes": len(data), "clip_windows": windows}


def persist_clip_pack_meta(work: Work, pack: dict) -> None:
    """Stamp clip-pack.zip on the work. Ready means a stored key, not just duration."""
    from app.services.stem_assets import stamp_post_process

    windows = pack.get("clip_windows") or []
    has_files = any(isinstance(row, dict) and row.get("file") for row in windows)
    if not pack.get("key") or not has_files:
        return
    stamp_post_process(
        work,
        clips={
            "clip_pack_key": pack["key"],
            "clip_pack_url": pack.get("url"),
            "clip_windows": windows,
        },
    )


def ensure_work_clip_pack(work: Work) -> tuple[bytes, str]:
    from fastapi import HTTPException

    from app.services.distribution.asset_profiles import clips_pack_ref

    storage = get_storage_service()
    existing = clips_pack_ref(work)
    if existing.get("key"):
        try:
            data = storage.get_object_bytes(existing["key"])
        except Exception:
            data = None
        if data:
            return data, str(existing.get("url") or "")
    audio = None
    if getattr(work, "storage_key", None):
        try:
            audio = storage.get_object_bytes(work.storage_key)
        except Exception:
            audio = None
    pack = build_clip_pack(work=work, audio_bytes=audio)
    persist_clip_pack_meta(work, pack)
    try:
        data = storage.get_object_bytes(pack["key"])
    except Exception as exc:
        raise HTTPException(502, "Clip pack storage unavailable") from exc
    if not data:
        raise HTTPException(502, "Clip pack storage unavailable")
    return data, pack["url"]


def _cover_bytes(work: Work, meta: ReleaseMetadata | None) -> bytes | None:
    url = (meta.cover_url if meta else None) or (getattr(work, "cover_url", None) or "")
    key = getattr(work, "cover_storage_key", None)
    if key:
        try:
            data = get_storage_service().get_object_bytes(key)
            if data:
                return data
        except Exception:
            pass
    if not url or not str(url).startswith("http"):
        return None
    try:
        import httpx

        resp = httpx.get(url, timeout=8, follow_redirects=True)
        resp.raise_for_status()
        if resp.content and len(resp.content) < 8_000_000:
            return resp.content
    except Exception:
        return None
    return None
