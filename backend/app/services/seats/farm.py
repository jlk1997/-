"""Remote browser farm host. Playwright when present; injected rows are debug-only."""

from __future__ import annotations

import logging
import time
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.models.schemas import CreatorSeat, SeatJob
from app.services.harvest.ingest import ingest_harvest_rows
from app.services.harvest.playbooks import PACKAGE_DIR, channel_playbook
from app.services.seats.service import complete_job, load_seat_session, release_job

logger = logging.getLogger(__name__)

PROFILE_ROOT = Path(__file__).resolve().parents[4] / "apps" / "browser-farm" / "profiles"


def _live_navigate() -> bool:
    from app.services.seats.service import farm_navigate_requested

    return farm_navigate_requested()


def farm_url_allowed(url: str | None, channel: str | None) -> bool:
    """Platform farm may only open that store's official hosts."""
    from urllib.parse import urlparse

    from app.services.distribution.catalog import channel_hosts

    host = (urlparse(url or "").hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if not host:
        return False
    allowed = [item.lower() for item in channel_hosts(channel) if item]
    return any(host == item or host.endswith(f".{item}") for item in allowed)


def _session_blob(session: dict | None) -> dict:
    payload = session or {}
    inner = payload.get("session") if isinstance(payload.get("session"), dict) else payload
    return inner if isinstance(inner, dict) else {}


def _session_cookies(session: dict | None) -> list:
    blob = _session_blob(session)
    cookies = blob.get("cookies")
    return list(cookies) if isinstance(cookies, list) else []


def _restore_storage_state(page, session: dict | None, channel: str | None) -> None:
    """Replay localStorage/sessionStorage from the connector snapshot. Never uses passwords."""
    blob = _session_blob(session)
    for origin in blob.get("origins") or []:
        if not isinstance(origin, dict):
            continue
        loc = str(origin.get("origin") or "").strip()
        if not loc or not farm_url_allowed(loc, channel):
            continue
        local_items = origin.get("localStorage") or []
        session_items = origin.get("sessionStorage") or []
        if not local_items and not session_items:
            continue
        try:
            page.goto(loc, wait_until="domcontentloaded", timeout=12000)
            page.evaluate(
                """(payload) => {
                    (payload.localStorage || []).forEach((item) => {
                      try { localStorage.setItem(item.name, item.value); } catch (e) {}
                    });
                    (payload.sessionStorage || []).forEach((item) => {
                      try { sessionStorage.setItem(item.name, item.value); } catch (e) {}
                    });
                }""",
                {"localStorage": local_items, "sessionStorage": session_items},
            )
        except Exception:
            continue


def clean_harvest_row(seat: CreatorSeat, row: dict) -> dict:
    return {
        "channel_code": row.get("channel_code") or seat.channel_code,
        "title": row.get("title"),
        "isrc": row.get("isrc"),
        "track_code": row.get("track_code"),
        "streams": int(row.get("streams") or 0),
        "revenue_minor": int(row.get("revenue_minor") or 0),
        "currency": row.get("currency") or "CNY",
        "period_key": row.get("period_key"),
        "external_track_id": row.get("external_track_id"),
        "content_hash": row.get("content_hash"),
        "confidence": row.get("confidence"),
        "extractor_version": row.get("extractor_version"),
    }


def profile_dir(seat: CreatorSeat) -> Path:
    name = seat.profile_id or str(seat.id)
    path = PROFILE_ROOT / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def run_job(db: Session, job: SeatJob) -> dict:
    seat = db.query(CreatorSeat).filter(CreatorSeat.id == job.seat_id).first()
    if not seat:
        return complete_job(db, str(job.id), ok=False, result={"error": "seat_missing"})
    payload = dict(job.payload or {})
    if job.kind == "harvest":
        return _run_harvest(db, job, seat, payload)
    if job.kind == "sync_metrics":
        return _run_sync(db, job, seat, payload)
    if job.kind == "open_portal":
        return release_job(db, job, reason="handed_to_extension")
    if job.kind == "health":
        playbook = channel_playbook(seat.channel_code)
        extra = dict(seat.extra or {})
        extra["farm_health"] = {
            "ok": True,
            "playbook": playbook.get("name") if isinstance(playbook, dict) else playbook,
            "at": datetime.utcnow().isoformat(),
        }
        seat.extra = extra
        db.commit()
        return complete_job(db, str(job.id), ok=True, result={"ok": True, "playbook": playbook, **extra["farm_health"]})
    if job.kind == "relogin":
        extra = dict(seat.extra or {})
        if extra.get("has_session"):
            seat.status = "live"
            seat.last_error = None
        else:
            seat.status = "needs_challenge"
            extra["challenge"] = "relogin"
            seat.extra = extra
        db.commit()
        return complete_job(db, str(job.id), ok=True, result={"status": seat.status})
    if job.kind == "remote_login":
        return _run_remote_login(db, job, seat, payload)
    if job.kind == "upload":
        return _run_upload(db, job, seat, payload)
    return complete_job(db, str(job.id), ok=False, result={"error": "unknown_kind"})


def check_seat_health_proactive(db: Session, seat) -> dict:
    """Check seat session health and warn before expiry."""
    from app.services.alerting import alert

    extra = dict(seat.extra or {})
    last_healthy = extra.get("last_healthy_at")

    if seat.status == "needs_challenge":
        alert(
            "seat_needs_relogin",
            f"Seat {seat.id} ({seat.platform_code if hasattr(seat, 'platform_code') else seat.channel_code}) needs re-login",
            severity="warning",
            context={"seat_id": str(seat.id), "platform": getattr(seat, "platform_code", None) or seat.channel_code},
            dedupe_key=str(seat.id),
            dedupe_seconds=3600,
        )
        return {"healthy": False, "reason": "needs_challenge"}

    if last_healthy:
        from datetime import timedelta

        try:
            last = datetime.fromisoformat(str(last_healthy))
            if datetime.utcnow() - last > timedelta(days=3):
                alert(
                    "seat_session_stale",
                    f"Seat {seat.id} ({seat.channel_code}) session not verified in 3+ days",
                    severity="info",
                    context={"seat_id": str(seat.id), "last_healthy": str(last_healthy)},
                    dedupe_key=str(seat.id),
                    dedupe_seconds=86400,
                )
        except (ValueError, TypeError):
            pass

    return {"healthy": True}


def classify_empty_harvest(*, has_session: bool, seat_status: str | None, seat=None) -> dict:
    """Zero rows is a login wall or a broken selector — never a successful harvest."""
    from app.services.alerting import alert

    status = (seat_status or "").strip()
    needs_challenge = (not has_session) or status in ("needs_challenge", "expired", "needs_session")
    seat_id = str(seat.id) if seat else "unknown"
    channel = (seat.channel_code if seat else "unknown")

    if needs_challenge:
        alert(
            "seat_login_wall",
            f"Seat {seat_id} ({channel}) hit login wall during harvest",
            severity="warning",
            context={"seat_id": seat_id, "channel": channel, "seat_status": status},
            dedupe_key=seat_id,
            dedupe_seconds=3600,
        )
        return {
            "error": "needs_challenge",
            "selector_broke": False,
            "needs_challenge": True,
            "expired": (not has_session) or status == "expired",
        }

    alert(
        "selector_broke",
        f"Seat {seat_id} ({channel}) selectors broken — zero rows with active session",
        severity="warning",
        context={"seat_id": seat_id, "channel": channel, "seat_status": status},
        dedupe_key=seat_id,
        dedupe_seconds=3600,
    )
    from app.services.harvest.playbooks import heal_candidates

    return {
        "error": "selector_broke",
        "selector_broke": True,
        "needs_challenge": False,
        "expired": False,
        "heal_candidates": heal_candidates(channel),
    }


def _stamp_farm_health(seat: CreatorSeat, metrics: dict) -> None:
    extra = dict(seat.extra or {})
    extra["farm_health"] = {**metrics, "at": datetime.utcnow().isoformat()}
    if metrics.get("ok"):
        extra["last_healthy_at"] = datetime.utcnow().isoformat()
    seat.extra = extra


def _run_harvest(db: Session, job: SeatJob, seat: CreatorSeat, payload: dict) -> dict:
    started = time.monotonic()
    rows = list(payload.get("rows") or [])
    csv_used = False
    if not rows:
        from app.services.harvest.official_csv import parse_official_csv

        csv_text = payload.get("csv_text") or payload.get("official_csv")
        if csv_text:
            rows = parse_official_csv(str(csv_text), seat.channel_code)
            csv_used = bool(rows)
    playwright = False
    if not rows:
        rows = _try_playwright_extract(seat, db)
        playwright = bool(rows)
    if not rows:
        from app.services.seats.service import farm_can_navigate

        if not farm_can_navigate() and not payload.get("rows"):
            _stamp_farm_health(seat, {"ok": False, "handed_to_extension": True, "rows": 0})
            return release_job(db, job, reason="handed_to_extension")
        attempts = int(payload.get("farm_attempts") or 0) + 1
        job.payload = {**payload, "farm_attempts": attempts}
        db.flush()
        if attempts >= 3:
            _stamp_farm_health(seat, {"ok": False, "handed_to_extension": True, "rows": 0, "attempts": attempts})
            return release_job(db, job, reason="handed_to_extension")
        empty = classify_empty_harvest(
            has_session=bool((seat.extra or {}).get("has_session")),
            seat_status=seat.status,
            seat=seat,
        )
        _stamp_farm_health(
            seat,
            {
                "ok": False,
                **empty,
                "session_expired": empty["expired"],
                "rows": 0,
                "elapsed_ms": int((time.monotonic() - started) * 1000),
            },
        )
        return complete_job(
            db,
            str(job.id),
            ok=False,
            result={**empty, "needs_runtime": True},
        )
    from app.services.seats.consent import has_scope

    settle = seat.ownership != "user" or has_scope(seat, "settle")
    from app.models.schemas import User
    from fastapi import HTTPException

    owner = db.query(User).filter(User.id == seat.user_id).first() if getattr(seat, "user_id", None) else None
    try:
        ingested = ingest_harvest_rows(
            db,
            rows,
            seat=seat,
            actor=owner,
            source="farm_harvest" if settle else "connector_sync",
            settle=settle,
        )
    except HTTPException as exc:
        _stamp_farm_health(seat, {"ok": False, "license_blocked": True, "rows": 0})
        return complete_job(
            db,
            str(job.id),
            ok=False,
            result={"error": str(exc.detail), "license_blocked": True},
        )
    metrics = {
        "ok": True,
        "rows": len(rows),
        "matched": ingested.get("matched"),
        "playwright": playwright,
        "official_csv": csv_used,
        "session_expired": False,
        "handed_to_extension": False,
        "elapsed_ms": int((time.monotonic() - started) * 1000),
    }
    _stamp_farm_health(seat, metrics)
    return complete_job(
        db,
        str(job.id),
        ok=True,
        result={
            "matched": ingested.get("matched"),
            "unmatched_count": ingested.get("unmatched_count"),
            "periods": ingested.get("periods"),
            **metrics,
        },
    )


def _run_sync(db: Session, job: SeatJob, seat: CreatorSeat, payload: dict) -> dict:
    rows = [clean_harvest_row(seat, row) for row in (payload.get("rows") or []) if isinstance(row, dict)]
    if not rows:
        return release_job(db, job, reason="handed_to_extension")
    ingested = ingest_harvest_rows(db, rows, seat=seat, source="connector_sync", settle=False)
    extra = dict(seat.extra or {})
    extra["last_sync_at"] = datetime.utcnow().isoformat()
    extra["farm_health"] = {
        "ok": True,
        "rows": len(rows),
        "matched": ingested.get("matched"),
        "source": "farm_sync",
        "at": datetime.utcnow().isoformat(),
    }
    seat.extra = extra
    db.commit()
    return complete_job(db, str(job.id), ok=True, result={"rows": len(rows), "matched": ingested.get("matched"), "synced": True})


def _try_playwright_extract(seat: CreatorSeat, db: Session | None = None) -> list[dict]:
    from app.services.seats.service import farm_can_navigate

    if not farm_can_navigate():
        return []
    session = {}
    try:
        if db is not None:
            session = load_seat_session(db, seat)
    except Exception:
        session = {}
    playbook = channel_playbook(seat.channel_code)
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        logger.info("playwright missing; farm harvest needs injected rows for seat %s", seat.id)
        return []
    url = playbook.get("stats_url") or playbook.get("harvest_url") or playbook.get("portal")
    if not url or not farm_url_allowed(url, seat.channel_code):
        return []
    try:
        with sync_playwright() as pw:
            context = pw.chromium.launch_persistent_context(
                user_data_dir=str(profile_dir(seat)),
                headless=True,
            )
            cookies = _session_cookies(session)
            if cookies:
                context.add_cookies(cookies)
            page = context.pages[0] if context.pages else context.new_page()
            _restore_storage_state(page, session, seat.channel_code)
            harvest_js = PACKAGE_DIR / "harvest.js"
            runner_js = PACKAGE_DIR / "runner.js"
            if harvest_js.exists():
                page.add_init_script(path=str(harvest_js))
            if runner_js.exists():
                page.add_init_script(path=str(runner_js))
            page.goto(url, wait_until="domcontentloaded", timeout=20000)
            waited = False
            for sel in playbook.get("wait_selectors") or ["table", "[data-vibe-row]"]:
                try:
                    page.wait_for_selector(sel, timeout=8000)
                    waited = True
                    break
                except Exception:
                    continue
            if not waited:
                page.wait_for_timeout(800)
            for sel in playbook.get("export_selectors") or []:
                try:
                    page.click(sel, timeout=1500)
                    page.wait_for_timeout(800)
                    break
                except Exception:
                    continue
            try:
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            except Exception:
                pass
            rows: list[dict] = []
            if runner_js.exists():
                for _page_i in range(6):
                    result = page.evaluate(
                        """(code) => (window.VibeRunner && window.VibeRunner.run(document, code)) || { rows: [] }""",
                        seat.channel_code,
                    )
                    if isinstance(result, dict) and result.get("reason") == "needs_challenge" and db is not None:
                        from app.services.seats.service import mark_challenge

                        mark_challenge(db, seat, note="login_wall")
                        rows = []
                        break
                    incoming = list((result or {}).get("rows") or []) if isinstance(result, dict) else []
                    before = len(rows)
                    seen = {
                        (row.get("track_code"), row.get("title"), row.get("streams"), row.get("revenue_minor"))
                        for row in rows
                    }
                    for row in incoming:
                        if not isinstance(row, dict):
                            continue
                        key = (row.get("track_code"), row.get("title"), row.get("streams"), row.get("revenue_minor"))
                        if key in seen:
                            continue
                        seen.add(key)
                        rows.append(row)
                    clicked = False
                    for sel in (playbook.get("next_page_selectors") or [])[:2]:
                        try:
                            page.click(sel, timeout=1200)
                            page.wait_for_timeout(600)
                            clicked = True
                            break
                        except Exception:
                            continue
                    if not clicked or len(rows) == before:
                        break
            elif harvest_js.exists():
                rows = page.evaluate(
                    """(code) => {
                      const api = window.VibeHarvest;
                      if (!api) return [];
                      return (api.harvestChannel || api.harvestVisibleTables)(document, code) || [];
                    }""",
                    seat.channel_code,
                )
            context.close()
            return [clean_harvest_row(seat, row) for row in rows or [] if isinstance(row, dict)]
    except Exception:
        logger.exception("farm harvest failed for seat %s", seat.id)
        return []


def _run_upload(db: Session, job: SeatJob, seat: CreatorSeat, payload: dict) -> dict:
    from app.services.distribution.catalog import channel_automation_level

    level = str(payload.get("automation_level") or channel_automation_level(seat.channel_code))
    if level == "metrics_only":
        return complete_job(db, str(job.id), ok=False, result={"error": "metrics_only"})
    playbook = channel_playbook(seat.channel_code)
    title = payload.get("title_with_code") or payload.get("title")
    filled = _try_playwright_fill(seat, db, payload)
    store_url = payload.get("store_url") or filled.get("store_url")
    if not store_url:
        return release_job(db, job, reason="handed_to_extension")
    return complete_job(
        db,
        str(job.id),
        ok=True,
        result={
            "queued": not filled.get("filled"),
            "filled": filled.get("fields") or [],
            "title": title,
            "title_with_code": title,
            "isrc": payload.get("isrc"),
            "store_url": store_url,
            "note": "fields filled on authorized portal" if filled.get("filled") else "upload handed to farm or extension",
            "playbook": playbook,
        },
    )


def _run_remote_login(db: Session, job: SeatJob, seat: CreatorSeat, payload: dict) -> dict:
    from app.services.seats.service import enqueue_job

    playbook = channel_playbook(seat.channel_code)
    login_url = payload.get("login_url") or playbook.get("portal") or playbook.get("harvest_url")
    extra = dict(seat.extra or {})
    remote = dict(extra.get("remote") or {})
    cookies = _try_profile_cookies(seat) if payload.get("capture_session") else []
    if cookies:
        from app.services.seats.service import save_seat_session

        save_seat_session(db, seat, session={"cookies": cookies}, mark_live=True)
        remote.update({"login_url": login_url, "status": "ready"})
        extra["remote"] = remote
        extra["has_session"] = True
        seat.extra = extra
        db.flush()
        enqueue_job(db, seat, "harvest", {})
        return complete_job(
            db,
            str(job.id),
            ok=True,
            result={"status": "ready", "login_url": login_url, "captured": True},
        )
    remote.update({"login_url": login_url, "status": "waiting_login" if not payload.get("capture_session") else "user_finished"})
    shot = _try_playwright_screenshot(seat, db, login_url)
    if shot:
        remote["screenshot"] = shot
        remote["status"] = "awaiting_user"
    extra["remote"] = remote
    seat.extra = extra
    db.flush()
    return complete_job(
        db,
        str(job.id),
        ok=True,
        result={"status": remote["status"], "login_url": login_url, "has_screenshot": bool(shot), "captured": False},
    )


def _materialize_upload_files(seat: CreatorSeat, payload: dict) -> dict:
    """Write master / originality zip to the farm profile. Never use stems as listing audio."""
    dest = profile_dir(seat)
    out = {"master_path": None, "originality_path": None}
    master = _bytes_from_payload(
        payload,
        url_keys=("master_wav_url", "master_audio_url", "audio_url"),
        key_keys=("master_wav_key", "master_storage_key"),
    )
    evidence = _bytes_from_payload(
        payload,
        url_keys=("originality_zip_url",),
        key_keys=("originality_zip_key",),
    )
    if master:
        path = dest / "listing-master.bin"
        path.write_bytes(master)
        out["master_path"] = str(path)
    if evidence:
        path = dest / "originality.zip"
        path.write_bytes(evidence)
        out["originality_path"] = str(path)
    return out


def _bytes_from_payload(payload: dict, *, url_keys: tuple[str, ...], key_keys: tuple[str, ...]) -> bytes | None:
    from app.services.storage import get_storage_service

    for key_name in key_keys:
        key = payload.get(key_name)
        if not key:
            continue
        try:
            data = get_storage_service().get_object_bytes(key)
            if data:
                return data
        except Exception:
            continue
    for url_name in url_keys:
        url = payload.get(url_name)
        if not url or not str(url).startswith("http"):
            continue
        try:
            import httpx

            resp = httpx.get(url, timeout=30, follow_redirects=True)
            resp.raise_for_status()
            if resp.content:
                return resp.content
        except Exception:
            continue
    return None


def _try_playwright_fill(seat: CreatorSeat, db: Session, payload: dict) -> dict:
    playbook = channel_playbook(seat.channel_code)
    url = payload.get("upload_url") or playbook.get("upload_url") or playbook.get("portal")
    from app.services.seats.service import farm_can_navigate

    if not url or not farm_can_navigate() or not farm_url_allowed(url, seat.channel_code):
        return {"filled": False, "fields": [], "reason": "handed_to_runtime"}
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return {"filled": False, "fields": [], "reason": "playwright_missing"}
    session = {}
    try:
        session = load_seat_session(db, seat)
    except Exception:
        session = {}
    upload_js = PACKAGE_DIR / "upload.js"
    files = _materialize_upload_files(seat, payload)
    try:
        with sync_playwright() as pw:
            context = pw.chromium.launch_persistent_context(user_data_dir=str(profile_dir(seat)), headless=True)
            cookies = _session_cookies(session)
            if cookies:
                context.add_cookies(cookies)
            page = context.pages[0] if context.pages else context.new_page()
            _restore_storage_state(page, session, seat.channel_code)
            if upload_js.exists():
                page.add_init_script(path=str(upload_js))
            page.goto(url, wait_until="domcontentloaded", timeout=20000)
            result = page.evaluate(
                """(payload) => (window.VibeUpload && window.VibeUpload.fillAuthorizedForm(document, payload)) || { filled: [], ok: false }""",
                {
                    "title": payload.get("title_with_code") or payload.get("title"),
                    "title_with_code": payload.get("title_with_code"),
                    "artist_name": payload.get("artist_name"),
                    "isrc": payload.get("isrc"),
                    "channel": seat.channel_code,
                    "listing_asset": "master",
                },
            )
            fields = list((result or {}).get("filled") or [])
            file_inputs = page.query_selector_all("input[type=file]")
            master_el = None
            evidence_el = None
            for el in file_inputs:
                accept = (el.get_attribute("accept") or "").lower()
                name = f"{el.get_attribute('name') or ''} {el.get_attribute('id') or ''} {accept}"
                if any(token in name.lower() for token in ("stem", "proof", "original", "zip", "分轨", "证明")):
                    evidence_el = evidence_el or el
                elif "image" in accept or "cover" in name.lower():
                    continue
                else:
                    master_el = master_el or el
            if not master_el and file_inputs:
                master_el = file_inputs[0]
                if evidence_el is master_el:
                    master_el = file_inputs[0]
            from app.services.distribution.catalog import channel_automation_level

            can_plant = str(payload.get("automation_level") or channel_automation_level(seat.channel_code)) == "connector_full"
            if can_plant and master_el and files.get("master_path") and master_el != evidence_el:
                master_el.set_input_files(files["master_path"])
                fields.append("master")
            elif can_plant and master_el and files.get("master_path") and not evidence_el:
                master_el.set_input_files(files["master_path"])
                fields.append("master")
            if can_plant and evidence_el and files.get("originality_path") and evidence_el != master_el:
                evidence_el.set_input_files(files["originality_path"])
                fields.append("evidence")
            context.close()
            return {
                "filled": bool(fields),
                "fields": fields,
                "listing_asset": "master",
            }
    except Exception:
        logger.exception("farm upload fill failed for seat %s", seat.id)
        return {"filled": False, "fields": [], "reason": "fill_failed"}


def _try_profile_cookies(seat: CreatorSeat) -> list:
    """Read cookies from the authorized farm profile only. Never logs values."""
    from app.services.seats.service import farm_can_navigate

    if not farm_can_navigate():
        return []
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return []
    try:
        with sync_playwright() as pw:
            context = pw.chromium.launch_persistent_context(user_data_dir=str(profile_dir(seat)), headless=True)
            cookies = list(context.cookies() or [])
            context.close()
            return cookies
    except Exception:
        logger.info("farm profile has no capturable session for seat %s", seat.id)
        return []


def _try_playwright_screenshot(seat: CreatorSeat, db: Session, url: str | None) -> str | None:
    from app.services.seats.service import farm_can_navigate

    if not url or not farm_can_navigate() or not farm_url_allowed(url, seat.channel_code):
        return None
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return None
    session = {}
    try:
        session = load_seat_session(db, seat)
    except Exception:
        session = {}
    try:
        with sync_playwright() as pw:
            context = pw.chromium.launch_persistent_context(user_data_dir=str(profile_dir(seat)), headless=True)
            cookies = _session_cookies(session)
            if cookies:
                context.add_cookies(cookies)
            page = context.pages[0] if context.pages else context.new_page()
            _restore_storage_state(page, session, seat.channel_code)
            page.goto(url, wait_until="domcontentloaded", timeout=20000)
            shot_path = profile_dir(seat) / "remote.jpg"
            page.screenshot(path=str(shot_path), type="jpeg", quality=40)
            context.close()
            import base64

            return "data:image/jpeg;base64," + base64.b64encode(shot_path.read_bytes()).decode("ascii")
    except Exception:
        logger.exception("farm remote screenshot failed for seat %s", seat.id)
        return None


def drain_queued(db: Session, *, limit: int = 20, seat_id: str | None = None) -> dict:
    from app.services.seats.service import lease_jobs
    from app.models.schemas import SeatJob

    patrol = (
        db.query(CreatorSeat)
        .filter(CreatorSeat.ownership == "platform")
        .order_by(CreatorSeat.updated_at.asc())
        .limit(12)
        .all()
    )
    patrol_failed = 0
    for seat in patrol:
        try:
            check_seat_health_proactive(db, seat)
        except Exception:
            patrol_failed += 1
            extra = dict(seat.extra or {})
            extra["patrol_error"] = True
            seat.extra = extra
            logger.exception("platform seat patrol failed for %s", seat.id)
    leased = lease_jobs(db, owner="farm", runtime="farm", limit=limit, seat_id=seat_id)
    ran = 0
    jobs_ok = 0
    jobs_fail = 0
    rows_ingested = 0
    seats_needing_challenge = 0
    handed_to_extension = 0
    for item in leased:
        job = db.query(SeatJob).filter(SeatJob.id == item["id"]).first()
        if not job:
            continue
        result = run_job(db, job) or {}
        ran += 1
        raw = result.get("result") if isinstance(result.get("result"), dict) else result
        if result.get("status") == "done":
            jobs_ok += 1
        elif result.get("handed_to_runtime"):
            handed_to_extension += 1
        else:
            jobs_fail += 1
        rows_ingested += int((raw or {}).get("matched") or (raw or {}).get("rows") or 0)
        if (raw or {}).get("needs_challenge") or (raw or {}).get("session_expired"):
            seats_needing_challenge += 1
        if (raw or {}).get("handed_to_extension") or (raw or {}).get("reason") == "handed_to_extension":
            handed_to_extension += 1
    return {
        "leased": len(leased),
        "ran": ran,
        "jobs_ok": jobs_ok,
        "jobs_fail": jobs_fail,
        "rows_ingested": rows_ingested,
        "seats_needing_challenge": seats_needing_challenge,
        "handed_to_extension": handed_to_extension,
        "patrol_failed": patrol_failed,
    }
