from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware
import logging

import json

from app.api.router import api_router
from app.config import settings
from app.database import SessionLocal, engine
from app.health import collect_health
from app.models.schemas import Challenge, FeatureFlag, Tenant, User
from app.core.style_presets import seed_builtin_presets
from app.migrations import run_migrations
from app.db_migrate import run_alembic_upgrade
from app.startup_checks import validate_production_config

log = logging.getLogger("vibe.startup")


class StructuredFormatter(logging.Formatter):
    def format(self, record):
        log_data = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if hasattr(record, "request_id"):
            log_data["request_id"] = record.request_id
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_data, ensure_ascii=False, default=str)


if not settings.debug:
    handler = logging.StreamHandler()
    handler.setFormatter(StructuredFormatter())
    logging.root.handlers = [handler]
    logging.root.setLevel(logging.INFO)

app = FastAPI(title=settings.app_name, version=settings.app_version)
app.add_middleware(GZipMiddleware, minimum_size=500)

if settings.metrics_enabled:
    from app.observability.metrics import MetricsMiddleware

    app.add_middleware(MetricsMiddleware)

from app.observability.request_id import RequestIdMiddleware

app.add_middleware(RequestIdMiddleware)

if settings.sentry_dsn:
    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.celery import CeleryIntegration
        from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            integrations=[FastApiIntegration(), CeleryIntegration(), SqlalchemyIntegration()],
            traces_sample_rate=settings.sentry_traces_sample_rate if settings.sentry_traces_sample_rate is not None else 0.1,
            environment=settings.sentry_environment or ("development" if settings.debug else "production"),
            release=settings.app_version,
        )
    except Exception as exc:
        log.warning("Sentry init failed: %s", exc)

_cors_kwargs: dict = {
    "allow_origins": settings.cors_origin_list,
    "allow_credentials": True,
    "allow_methods": ["*"],
    "allow_headers": ["*"],
}
# 开发模式：允许 localhost / 127.0.0.1 / 局域网 IP 任意端口（Taro H5 dev 10086 等）
if settings.debug:
    _cors_kwargs["allow_origin_regex"] = (
        r"http://(localhost|127\.0\.0\.1|192\.168\.\d{1,3}\.\d{1,3}|10\.\d{1,3}\.\d{1,3}\.\d{1,3})(:\d+)?"
    )

app.add_middleware(CORSMiddleware, **_cors_kwargs)


def seed_platform_defaults():
    db = SessionLocal()
    try:
        flags = [
            ("music_cover", settings.music_cover_enabled, "Enable AI cover generation during post-process"),
            ("hls_streaming", True, "Enable HLS transcoding"),
            ("c2pa_provenance", settings.c2pa_enabled, "Enable C2PA manifests"),
            ("personalized_feed", True, "Enable embedding-based feed ranking"),
            (
                "credits_gate",
                settings.credits_gate_enabled,
                "Enable generation credits gate (402 when insufficient)",
            ),
            ("multi_tenant", False, "Enable tenant_id isolation on feed and works"),
            ("dsp_distribution", True, "Enable DSP distribution and creator releases"),
            ("royalty_wallet", True, "Enable fiat royalty wallet and withdrawals"),
            ("release_qc", True, "Enable release-ready QC before distribution"),
        ]
        for key, enabled, desc in flags:
            row = db.query(FeatureFlag).filter(FeatureFlag.key == key).first()
            if not row:
                db.add(FeatureFlag(key=key, enabled=enabled, description=desc))
            elif key == "credits_gate" and settings.credits_gate_enabled and not row.enabled:
                row.enabled = True
            elif key == "music_cover" and settings.music_cover_enabled and not row.enabled:
                row.enabled = True
        if not db.query(Challenge).filter(Challenge.slug == "calm-to-chaos").first():
            db.add(Challenge(
                slug="calm-to-chaos",
                title="Calm to Chaos 情绪挑战",
                description="从平静到混沌，用 6 首作品讲述你的情绪旅程",
                hashtag="CalmToChaos",
                target_curve="calm_to_energy",
            ))
        if settings.admin_bootstrap_email.strip():
            bootstrap_email = settings.admin_bootstrap_email.strip().lower()
            if not db.query(User).filter(User.is_admin == True).first():
                candidate = db.query(User).filter(User.email == bootstrap_email).first()
                if candidate and not candidate.is_admin:
                    candidate.is_admin = True
        if not db.query(Tenant).filter(Tenant.id == settings.default_tenant_id).first():
            db.add(Tenant(id=settings.default_tenant_id, name="Default", plan="free"))
        seed_builtin_presets(db)
        from app.services.content_moderation import seed_default_words
        from app.services.distribution.catalog import seed_distribution_catalog

        seed_default_words(db)
        seed_distribution_catalog(db)
        from app.services.ecosystem import seed_recipe_catalog

        seed_recipe_catalog(db)
        from app.services.workbench import seed_official_effect_packs

        seed_official_effect_packs(db)
        from app.services.catalog_seed import seed_official_catalog

        seed_official_catalog(db)
        from app.services.seats.service import ensure_platform_seats

        ensure_platform_seats(db, pool_size=int(getattr(settings, "platform_seat_pool_size", 1) or 1))
        db.commit()
    except Exception:
        log.exception("seed_platform_defaults failed; catalog/radio may stay empty")
        db.rollback()
    finally:
        db.close()


def _ensure_pgvector():
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))


def _startup_progress(msg: str) -> None:
    """Visible during Alembic fileConfig (root logger may be WARN)."""
    print(f"[vibe.startup] {msg}", flush=True)
    log.info(msg)


def run_startup_tasks() -> None:
    _startup_progress("Validating config…")
    validate_production_config()
    _startup_progress("Ensuring pgvector extension…")
    _ensure_pgvector()
    if settings.run_alembic_on_startup:
        _startup_progress("Running Alembic migrations…")
        run_alembic_upgrade()
    else:
        _startup_progress("Skipping Alembic on startup (RUN_ALEMBIC_ON_STARTUP=false)")
    _startup_progress("Running legacy column backfill…")
    run_migrations()
    _startup_progress("Seeding platform defaults…")
    seed_platform_defaults()
    _startup_progress("Application startup complete.")


@app.on_event("startup")
def startup():
    run_startup_tasks()


@app.get("/health")
@app.get("/api/v1/health")
def readiness():
    from fastapi.responses import JSONResponse
    result = collect_health()
    status_val = result.get("status", "ok") if isinstance(result, dict) else "ok"
    code = 200 if status_val == "ok" else 503
    return JSONResponse(content=result, status_code=code)


@app.get("/livez")
@app.get("/api/v1/livez")
def liveness():
    return {"status": "alive"}


@app.get("/health/worker")
@app.get("/api/v1/health/worker")
def health_worker():
    from app.health import collect_worker_health

    return collect_worker_health()


@app.get("/metrics")
def metrics(request: Request):
    from fastapi.responses import PlainTextResponse
    from app.observability.metrics import prometheus_text

    token = settings.metrics_token
    if not token and not settings.debug:
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="Metrics token not configured")
    if token:
        auth = request.headers.get("Authorization", "")
        if auth != f"Bearer {token}":
            from fastapi import HTTPException
            raise HTTPException(status_code=403, detail="Invalid metrics token")
    return PlainTextResponse(prometheus_text(), media_type="text/plain; version=0.0.4")


app.include_router(api_router, prefix=settings.api_prefix)
