from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_current_user_or_connector, security
from app.api.surface import require_h5_desk
from app.database import get_db
from app.models.schemas import User
from app.services.distribution import service as dist
from app.services.royalty import connector as connector_svc
from app.services.royalty import sync as analytics_sync
from app.services.royalty import youtube as youtube_oauth

router = APIRouter(prefix="/distribution", tags=["distribution"])


class StoreUrlBody(BaseModel):
    store_url: str
    external_id: str | None = None


class BindingBody(BaseModel):
    provider: str
    official_token: str | None = None
    external_release_id: str | None = None


class ConnectorRow(BaseModel):
    channel_code: str | None = None
    period_key: str | None = None
    external_track_id: str | None = None
    work_id: str | None = None
    user_id: str | None = None
    title: str | None = None
    isrc: str | None = None
    streams: int = 0
    saves: int = 0
    comments: int = 0
    revenue_minor: int = 0
    currency: str = "CNY"
    confidence: float = 0.5
    raw: dict | None = None


class ConnectorIngestBody(BaseModel):
    channel_code: str | None = None
    period_key: str | None = None
    rows: list[ConnectorRow] = Field(default_factory=list)


class ClaimMatchBody(BaseModel):
    work_id: str


class AssistCompleteBody(BaseModel):
    store_url: str
    external_id: str | None = None


class AssistProgressBody(BaseModel):
    event: str
    message: str | None = None


class HeartbeatBody(BaseModel):
    extension_version: str | None = None
    channel: str | None = None
    period_key: str | None = None
    last_harvest: dict | None = None
    last_progress: dict | None = None


def get_connector_actor(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    x_connector_token: str | None = Header(default=None, alias="X-Connector-Token"),
    db: Session = Depends(get_db),
) -> connector_svc.ConnectorActor:
    token = (credentials.credentials if credentials else None) or x_connector_token
    actor = connector_svc.resolve_connector_actor(db, token or "")
    if not actor:
        raise HTTPException(401, "Invalid connector token")
    return actor


@router.post("/partner/webhook")
async def partner_webhook(
    request: Request,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
    x_vibe_signature: str | None = Header(default=None, alias="X-Vibe-Signature"),
):
    from app.api.rate_limits import check_webhook_rate_limit
    from app.services.distribution.partner_events import handle_partner_webhook

    check_webhook_rate_limit(request)
    body = await request.body()
    return handle_partner_webhook(db, body=body, authorization=authorization, signature=x_vibe_signature)


@router.get("/deliveries")
def deliveries(work_id: str | None = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return {"deliveries": dist.list_user_deliveries(db, user, work_id)}


@router.post("/deliveries/{delivery_id}/retry")
def retry(
    delivery_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _desk: None = Depends(require_h5_desk),
):
    return dist.retry_delivery(db, user, delivery_id)


@router.post("/deliveries/{delivery_id}/store-url")
def store_url(
    delivery_id: str,
    payload: StoreUrlBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _desk: None = Depends(require_h5_desk),
):
    return dist.set_store_url(db, user, delivery_id, payload.store_url, payload.external_id)


@router.get("/bindings")
def bindings(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return {"bindings": dist.list_bindings(db, user)}


@router.post("/bindings")
def bind(
    payload: BindingBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _desk: None = Depends(require_h5_desk),
):
    return dist.bind_distributor(db, user, payload.provider, payload.official_token, payload.external_release_id)


@router.delete("/bindings/{provider}")
def unbind(
    provider: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _desk: None = Depends(require_h5_desk),
):
    return dist.unbind_distributor(db, user, provider)


@router.get("/analytics/sources")
def analytics_sources(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return analytics_sync.list_analytics_sources(db, user)


@router.post("/analytics/sync")
def analytics_sync_now(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _desk: None = Depends(require_h5_desk),
):
    return analytics_sync.sync_user_analytics(db, user)


@router.get("/connector/schema")
def connector_schema():
    return {"schema": connector_svc.CONNECTOR_SCHEMA, "sources": ["ops_connector", "user_connector"]}


@router.post("/connector/token")
def connector_token(user: User = Depends(get_current_user), db: Session = Depends(get_db), _desk: None = Depends(require_h5_desk)):
    return connector_svc.mint_ingest_token(db, user)


@router.delete("/connector/token")
def revoke_connector_token(
    user: User = Depends(get_current_user_or_connector),
    db: Session = Depends(get_db),
    _desk: None = Depends(require_h5_desk),
):
    return connector_svc.revoke_connector_tokens(db, user)


@router.post("/connector/ingest")
def connector_ingest(payload: ConnectorIngestBody, actor: connector_svc.ConnectorActor = Depends(get_connector_actor), db: Session = Depends(get_db)):
    return connector_svc.ingest_connector_rows(db, actor, payload.model_dump())


@router.get("/connector/claims")
def connector_claims(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return {"claims": connector_svc.list_claims(db, user_id=user.id)}


@router.post("/connector/claims/{claim_id}/match")
def connector_match_claim(
    claim_id: str,
    payload: ClaimMatchBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _desk: None = Depends(require_h5_desk),
):
    return connector_svc.match_claim(db, claim_id, payload.work_id, user, admin=bool(getattr(user, "is_admin", False)))


@router.post("/assist/heartbeat")
async def assist_heartbeat(
    request: Request,
    actor: connector_svc.ConnectorActor = Depends(get_connector_actor),
    db: Session = Depends(get_db),
):
    from app.services.distribution.assist import touch_heartbeat

    raw: dict = {}
    try:
        if request.headers.get("content-length") not in (None, "0"):
            parsed = await request.json()
            if isinstance(parsed, dict):
                raw = HeartbeatBody(**parsed).model_dump(exclude_none=True)
    except Exception:
        raw = {}
    return touch_heartbeat(db, actor.user, raw or None)


@router.get("/assist/jobs")
def assist_jobs(actor: connector_svc.ConnectorActor = Depends(get_connector_actor), db: Session = Depends(get_db)):
    from app.services.distribution.assist import list_assist_jobs

    return {"jobs": list_assist_jobs(db, actor.user)}


@router.post("/assist/jobs/{delivery_id}/claim")
def assist_claim(
    delivery_id: str,
    actor: connector_svc.ConnectorActor = Depends(get_connector_actor),
    db: Session = Depends(get_db),
):
    from app.services.distribution.assist import claim_assist_job

    return claim_assist_job(db, actor.user, delivery_id)


@router.post("/assist/jobs/{delivery_id}/complete")
def assist_complete(
    delivery_id: str,
    payload: AssistCompleteBody,
    actor: connector_svc.ConnectorActor = Depends(get_connector_actor),
    db: Session = Depends(get_db),
):
    from app.services.distribution.assist import complete_assist_job

    return complete_assist_job(db, actor.user, delivery_id, store_url=payload.store_url, external_id=payload.external_id)


@router.post("/assist/jobs/{delivery_id}/progress")
def assist_progress(
    delivery_id: str,
    payload: AssistProgressBody,
    actor: connector_svc.ConnectorActor = Depends(get_connector_actor),
    db: Session = Depends(get_db),
):
    from app.services.distribution.assist import note_assist_progress

    return note_assist_progress(db, actor.user, delivery_id, event=payload.event, message=payload.message)


@router.get("/assist/jobs/{delivery_id}/kit")
def assist_kit(
    delivery_id: str,
    actor: connector_svc.ConnectorActor = Depends(get_connector_actor),
    db: Session = Depends(get_db),
):
    from app.services.distribution.assist import assist_kit_payload

    return assist_kit_payload(db, actor.user, delivery_id)


def _stream_assist_asset(request: Request, asset: dict) -> Response:
    data = asset.get("bytes") or b""
    total = len(data)
    etag = str(asset.get("etag") or "")
    if request.headers.get("if-none-match") == etag and etag:
        return Response(status_code=304, headers={"ETag": etag})
    start, end = 0, total - 1 if total else 0
    status = 200
    range_header = request.headers.get("range") or ""
    if range_header.lower().startswith("bytes=") and total:
        spec = range_header.split("=", 1)[1]
        left, _, right = spec.partition("-")
        try:
            start = int(left) if left else 0
            end = int(right) if right else total - 1
        except ValueError:
            start, end = 0, total - 1
        start = max(0, min(start, total - 1))
        end = max(start, min(end, total - 1))
        status = 206
    chunk = data[start : end + 1] if total else b""
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(len(chunk)),
        "Content-Disposition": f'attachment; filename="{asset.get("filename") or "asset"}"',
        "ETag": etag,
        "Cache-Control": "private, max-age=60",
        "X-Listing-Asset": "master",
    }
    if status == 206:
        headers["Content-Range"] = f"bytes {start}-{end}/{total}"
    return Response(content=chunk, status_code=status, media_type=asset.get("content_type") or "application/octet-stream", headers=headers)


@router.get("/assist/jobs/{delivery_id}/master")
def assist_master(
    delivery_id: str,
    request: Request,
    actor: connector_svc.ConnectorActor = Depends(get_connector_actor),
    db: Session = Depends(get_db),
):
    from app.services.distribution.assist import assist_asset_bytes

    return _stream_assist_asset(request, assist_asset_bytes(db, actor.user, delivery_id, "master"))


@router.get("/assist/jobs/{delivery_id}/originality-file")
def assist_originality_file(
    delivery_id: str,
    request: Request,
    actor: connector_svc.ConnectorActor = Depends(get_connector_actor),
    db: Session = Depends(get_db),
):
    from app.services.distribution.assist import assist_asset_bytes

    return _stream_assist_asset(request, assist_asset_bytes(db, actor.user, delivery_id, "originality"))


@router.get("/assist/jobs/{delivery_id}/originality")
def assist_originality(
    delivery_id: str,
    actor: connector_svc.ConnectorActor = Depends(get_connector_actor),
    db: Session = Depends(get_db),
):
    from app.services.distribution.assist import assist_kit_payload

    payload = assist_kit_payload(db, actor.user, delivery_id)
    return {
        "delivery_id": str(payload.get("delivery_id") or delivery_id),
        "channel_code": payload.get("channel_code"),
        "originality_zip_url": payload.get("originality_zip_url"),
        "listing_asset": "master",
        "note": "CN originality evidence only. Do not upload as the listing audio.",
    }


@router.get("/assist/jobs/{delivery_id}/clip-pack")
def assist_clip_pack(
    delivery_id: str,
    actor: connector_svc.ConnectorActor = Depends(get_connector_actor),
    db: Session = Depends(get_db),
):
    from app.services.distribution.assist import assist_kit_payload

    payload = assist_kit_payload(db, actor.user, delivery_id)
    return {"clip_pack_url": payload.get("clip_pack_url"), "clip_windows": payload.get("clip_windows") or []}


@router.get("/youtube/oauth-url")
def youtube_oauth_url(user: User = Depends(get_current_user), _desk: None = Depends(require_h5_desk)):
    return {"configured": youtube_oauth.configured(), "url": youtube_oauth.auth_url(str(user.id)) if youtube_oauth.configured() else None}


@router.get("/youtube/callback")
def youtube_callback(code: str = "", state: str = "", error: str | None = None, db: Session = Depends(get_db)):
    target = youtube_oauth.frontend_redirect()
    if error or not code or not state:
        return RedirectResponse(target.replace("connected", "error"))
    try:
        youtube_oauth.exchange_code(code, state, db)
    except Exception:
        return RedirectResponse(target.replace("connected", "error"))
    return RedirectResponse(target)
