"""Official distributor adapters. Partner webhook only — no scrape, no stored passwords."""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.config import settings


def _listing_audio_url(work: dict) -> str | None:
    return work.get("master_wav_url") or work.get("audio_url")


def _ai_flags(work: dict) -> dict:
    generated = bool(work.get("ai_generated", True))
    return {
        "ai_generated": generated,
        "ai_disclosed": bool(work.get("ai_disclosed", generated)),
    }


def _instrumental_flag(work: dict) -> bool:
    return bool(work.get("instrumental") or work.get("sku_kind") == "instrumental")


ALLOWED_STATUSES = {
    "submitting",
    "ops_queue",
    "awaiting_manual",
    "session_wait",
    "session_running",
    "in_review",
    "live",
    "rejected",
    "taken_down",
}


@dataclass
class AdapterResult:
    ok: bool
    status: str
    external_id: str | None = None
    message: str | None = None
    kit_required: bool = False
    store_url: str | None = None
    isrc: str | None = None
    upc: str | None = None


class DistributorAdapter:
    provider = "base"
    key_attr = ""
    base_attr = ""

    def _key(self) -> str:
        return (getattr(settings, self.key_attr, "") or "").strip() if self.key_attr else ""

    def _base(self) -> str:
        return (getattr(settings, self.base_attr, "") or "").rstrip("/") if self.base_attr else ""

    def has_credentials(self) -> bool:
        return bool(self._key())

    def configured(self) -> bool:
        return bool(self._key() and self._base())

    def submit(self, payload: dict) -> AdapterResult:
        if not self._key():
            return AdapterResult(
                ok=True,
                status="ops_queue",
                kit_required=True,
                message="进运营队列，不是故障：合作方还没有密钥，由运营代投。",
            )
        if not self._base():
            return AdapterResult(
                ok=True,
                status="ops_queue",
                kit_required=True,
                message="进运营队列，不是故障：已有密钥但没有合作端点。",
            )
        return self._partner_submit(payload)

    def query_status(self, external_id: str | None) -> AdapterResult:
        if not self.configured() or not external_id:
            return AdapterResult(ok=True, status="in_review", external_id=external_id)
        try:
            resp = httpx.get(
                f"{self._base()}/v1/deliveries/{external_id}",
                headers={"Authorization": f"Bearer {self._key()}", "Accept": "application/json"},
                timeout=20,
            )
            resp.raise_for_status()
            body = resp.json() if resp.content else {}
        except Exception as exc:
            return AdapterResult(ok=False, status="in_review", external_id=external_id, message=str(exc)[:300])
        status = str(body.get("status") or "in_review")
        if status not in ALLOWED_STATUSES:
            status = "in_review"
        store_url = body.get("store_url") or body.get("url")
        return AdapterResult(
            ok=True,
            status=status,
            external_id=body.get("external_id") or external_id,
            message=body.get("message"),
            store_url=str(store_url) if store_url else None,
            isrc=str(body.get("isrc") or "")[:15] or None,
            upc=str(body.get("upc") or "")[:32] or None,
        )

    def takedown(self, external_id: str | None) -> AdapterResult:
        if not self.configured():
            return AdapterResult(ok=True, status="awaiting_manual", external_id=external_id, message="请在分发商后台人工下架")
        if not external_id:
            return AdapterResult(ok=True, status="taken_down", external_id=external_id)
        try:
            resp = httpx.post(
                f"{self._base()}/v1/deliveries/{external_id}/takedown",
                headers={"Authorization": f"Bearer {self._key()}", "Accept": "application/json"},
                timeout=20,
            )
            resp.raise_for_status()
            body = resp.json() if resp.content else {}
        except Exception as exc:
            return AdapterResult(ok=False, status="awaiting_manual", external_id=external_id, message=str(exc)[:300])
        return AdapterResult(ok=True, status="taken_down", external_id=body.get("external_id") or external_id)

    def parse_webhook(self, payload: dict) -> dict | None:
        """Normalize a provider-shaped callback. Return None to keep the generic payload."""
        return None

    def build_payload(self, release: dict, delivery: dict, work: dict) -> dict:
        """Build provider-specific submission payload from our domain objects.

        Override in subclasses for provider-specific field mapping.
        Default returns the generic format used by the stub partner API.
        """
        return {
            "provider": self.provider,
            "title": work.get("title", ""),
            "artist_name": work.get("artist_name", ""),
            "isrc": work.get("isrc") or delivery.get("track_code"),
            "upc": release.get("upc"),
            "audio_url": _listing_audio_url(work),
            "cover_url": work.get("cover_url"),
            "genres": work.get("genres", []),
            "release_date": release.get("release_date"),
            "territories": release.get("territories", ["worldwide"]),
            "language": work.get("language", "en"),
            "delivery_id": delivery.get("id"),
            "listing_asset": "master",
            "instrumental": _instrumental_flag(work),
            **_ai_flags(work),
        }

    def verify_webhook_signature(self, body: bytes, signature: str | None) -> bool:
        """Verify provider webhook signature. Override for provider-specific schemes."""
        import hashlib
        import hmac

        secret = (getattr(settings, "partner_webhook_secret", "") or "").strip()
        if not secret:
            return bool(settings.debug)
        if not signature:
            return False
        expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)

    def fetch_earnings(self, token: str | None = None) -> list[dict]:
        """Fetch earnings rows. Each row should contain: channel_code, title, isrc/track_code,
        revenue_minor, currency, period_key, streams."""
        key = (token or self._key()).strip()
        if not key or not self._base():
            return []
        try:
            resp = httpx.get(
                f"{self._base()}/v1/earnings",
                headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
                timeout=20,
            )
            resp.raise_for_status()
            body = resp.json() if resp.content else {}
        except Exception:
            return []
        rows = body.get("rows") if isinstance(body, dict) else body
        return [row for row in rows or [] if isinstance(row, dict)]

    def _partner_submit(self, payload: dict) -> AdapterResult:
        built = self.build_payload(
            payload.get("release", {}),
            payload.get("delivery", {}),
            payload.get("work", {}),
        ) if any(k in payload for k in ("release", "delivery", "work")) else payload
        try:
            resp = httpx.post(
                f"{self._base()}/v1/deliveries",
                headers={
                    "Authorization": f"Bearer {self._key()}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                json={"provider": self.provider, **built},
                timeout=30,
            )
            if resp.status_code >= 400:
                return AdapterResult(
                    ok=False,
                    status="submitting",
                    message=f"partner HTTP {resp.status_code}: {(resp.text or '')[:200]}",
                )
            body = resp.json() if resp.content else {}
        except Exception as exc:
            return AdapterResult(ok=False, status="submitting", message=str(exc)[:300])
        status = str(body.get("status") or "in_review")
        if status not in ALLOWED_STATUSES:
            status = "in_review"
        store_url = body.get("store_url") or body.get("url")
        return AdapterResult(
            ok=True,
            status=status,
            external_id=body.get("external_id"),
            message=body.get("message") or "已提交合作端点",
            kit_required=bool(body.get("kit_required")),
            store_url=str(store_url) if store_url else None,
            isrc=str(body.get("isrc") or "")[:15] or None,
            upc=str(body.get("upc") or "")[:32] or None,
        )


class DistroKidAdapter(DistributorAdapter):
    provider = "distrokid"
    key_attr = "distrokid_api_key"
    base_attr = "distrokid_api_base"

    def build_payload(self, release: dict, delivery: dict, work: dict) -> dict:
        """DistroKid album shape: one stereo master per track list. Never send stems as extra songs."""
        return {
            "provider": self.provider,
            "album": {
                "title": work.get("title", ""),
                "artist": work.get("artist_name", ""),
                "isrc": work.get("isrc") or delivery.get("track_code"),
                "upc": release.get("upc"),
                "genre": (work.get("genres") or ["Other"])[0],
                "subgenre": (work.get("genres") or ["", ""])[1] if len(work.get("genres", [])) > 1 else "",
                "release_date": release.get("release_date"),
                "cover_url": work.get("cover_url"),
                "language": work.get("language", "en"),
                "territories": release.get("territories", ["worldwide"]),
            },
            "tracks": [{
                "title": work.get("title", ""),
                "audio_url": _listing_audio_url(work),
                "isrc": work.get("isrc") or delivery.get("track_code"),
                "duration_ms": work.get("duration_ms"),
                "explicit": work.get("explicit", False),
                "instrumental": _instrumental_flag(work),
            }],
            "listing_asset": "master",
            **_ai_flags(work),
            "delivery_id": delivery.get("id"),
        }

    def parse_webhook(self, payload: dict) -> dict | None:
        if not any(k in payload for k in ("release_id", "dk_status", "store_link")):
            return None
        status = str(payload.get("status") or payload.get("dk_status") or payload.get("state") or "")
        mapped = {
            "live": "live",
            "approved": "live",
            "rejected": "rejected",
            "takedown": "taken_down",
            "taken_down": "taken_down",
        }.get(status.lower(), status if status in ALLOWED_STATUSES else None)
        if not mapped:
            return None
        return {
            "external_id": payload.get("external_id") or payload.get("release_id"),
            "delivery_id": payload.get("delivery_id"),
            "status": mapped,
            "store_url": payload.get("store_url") or payload.get("store_link"),
            "event_id": payload.get("event_id") or payload.get("id"),
            "message": payload.get("message") or "distrokid webhook",
            "isrc": payload.get("isrc"),
            "upc": payload.get("upc"),
        }


class TuneCoreAdapter(DistributorAdapter):
    provider = "tunecore"
    key_attr = "tunecore_api_key"
    base_attr = "tunecore_api_base"

    def build_payload(self, release: dict, delivery: dict, work: dict) -> dict:
        """TuneCore-specific payload: flat release shape."""
        return {
            "provider": self.provider,
            "title": work.get("title", ""),
            "primary_artist": work.get("artist_name", ""),
            "isrc": work.get("isrc") or delivery.get("track_code"),
            "upc": release.get("upc"),
            "audio_url": _listing_audio_url(work),
            "cover_url": work.get("cover_url"),
            "genre": (work.get("genres") or ["Other"])[0],
            "release_date": release.get("release_date"),
            "territories": release.get("territories", ["worldwide"]),
            "language": work.get("language", "en"),
            "delivery_id": delivery.get("id"),
            "explicit": work.get("explicit", False),
            "instrumental": _instrumental_flag(work),
            "listing_asset": "master",
            **_ai_flags(work),
        }

    def parse_webhook(self, payload: dict) -> dict | None:
        if not any(k in payload for k in ("tunecore_id", "upc", "tc_status")):
            return None
        status = str(payload.get("status") or payload.get("tc_status") or payload.get("state") or "")
        mapped = {
            "live": "live",
            "distributed": "live",
            "rejected": "rejected",
            "taken_down": "taken_down",
        }.get(status.lower(), status if status in ALLOWED_STATUSES else None)
        if not mapped:
            return None
        return {
            "external_id": payload.get("external_id") or payload.get("tunecore_id") or payload.get("upc"),
            "delivery_id": payload.get("delivery_id"),
            "status": mapped,
            "store_url": payload.get("store_url") or payload.get("store_link"),
            "event_id": payload.get("event_id") or payload.get("id"),
            "message": payload.get("message") or "tunecore webhook",
        }


class RouteNoteAdapter(DistributorAdapter):
    provider = "routenote"
    key_attr = "routenote_api_key"
    base_attr = "routenote_api_base"

    def build_payload(self, release: dict, delivery: dict, work: dict) -> dict:
        """RouteNote-specific payload: release + track nested shape."""
        return {
            "provider": self.provider,
            "release": {
                "title": work.get("title", ""),
                "artist": work.get("artist_name", ""),
                "upc": release.get("upc"),
                "cover_url": work.get("cover_url"),
                "release_date": release.get("release_date"),
                "territories": release.get("territories", ["worldwide"]),
                "language": work.get("language", "en"),
            },
            "track": {
                "title": work.get("title", ""),
                "isrc": work.get("isrc") or delivery.get("track_code"),
                "audio_url": _listing_audio_url(work),
                "genre": (work.get("genres") or ["Other"])[0],
                "duration_ms": work.get("duration_ms"),
                "explicit": work.get("explicit", False),
                "instrumental": _instrumental_flag(work),
            },
            "listing_asset": "master",
            **_ai_flags(work),
            "delivery_id": delivery.get("id"),
        }

    def parse_webhook(self, payload: dict) -> dict | None:
        if not any(k in payload for k in ("routenote_id", "rn_status", "barcode")):
            return None
        status = str(payload.get("status") or payload.get("rn_status") or payload.get("state") or "")
        mapped = {
            "live": "live",
            "released": "live",
            "rejected": "rejected",
            "taken_down": "taken_down",
        }.get(status.lower(), status if status in ALLOWED_STATUSES else None)
        if not mapped:
            return None
        return {
            "external_id": payload.get("external_id") or payload.get("routenote_id") or payload.get("barcode"),
            "delivery_id": payload.get("delivery_id"),
            "status": mapped,
            "store_url": payload.get("store_url") or payload.get("store_link"),
            "event_id": payload.get("event_id") or payload.get("id"),
            "message": payload.get("message") or "routenote webhook",
        }


class CnLabelAdapter(DistributorAdapter):
    provider = "cn_label"
    key_attr = "cn_label_api_key"
    base_attr = "cn_label_api_base"

    def build_payload(self, release: dict, delivery: dict, work: dict) -> dict:
        """CN label: one mixed master. Stems go in originality zip, not extra tracks."""
        payload = super().build_payload(release, delivery, work)
        payload["listing_asset"] = "master"
        payload.pop("stems", None)
        payload.pop("originality_zip_url", None)
        return payload

    def parse_webhook(self, payload: dict) -> dict | None:
        if not any(k in payload for k in ("cn_label_id", "label_status", "upc")):
            return None
        status = str(payload.get("status") or payload.get("label_status") or payload.get("state") or "")
        mapped = {
            "live": "live",
            "online": "live",
            "rejected": "rejected",
            "taken_down": "taken_down",
        }.get(status.lower(), status if status in ALLOWED_STATUSES else None)
        if not mapped:
            return None
        return {
            "external_id": payload.get("external_id") or payload.get("cn_label_id") or payload.get("upc"),
            "delivery_id": payload.get("delivery_id"),
            "status": mapped,
            "store_url": payload.get("store_url") or payload.get("store_link"),
            "event_id": payload.get("event_id") or payload.get("id"),
            "message": payload.get("message") or "cn_label webhook",
        }


class SessionAdapter(DistributorAdapter):
    provider = "session"

    def configured(self) -> bool:
        return False

    def submit(self, payload: dict) -> AdapterResult:
        return AdapterResult(
            ok=True,
            status="session_wait",
            kit_required=True,
            message="等待创作者或厂牌助手在已登录的官方页投递",
        )


ADAPTERS: dict[str, DistributorAdapter] = {
    "distrokid": DistroKidAdapter(),
    "tunecore": TuneCoreAdapter(),
    "routenote": RouteNoteAdapter(),
    "cn_label": CnLabelAdapter(),
    "session": SessionAdapter(),
}


def get_adapter(provider: str) -> DistributorAdapter:
    return ADAPTERS.get(provider, DistributorAdapter())
