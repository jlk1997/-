from fastapi import APIRouter

from app.api.routes import admin, analytics, auth, billing, challenges, collections, community, config, copilot, creator, distribution, ecosystem, emotion, engagement, jobs, legal, notifications, ops_console, playlists, provenance, releases, search, seats, studio, sync_desk, tenant_admin, users, wallet, wechat_auth, workbench, works
from app.config import settings

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(legal.router)
api_router.include_router(users.router)
api_router.include_router(emotion.router)
api_router.include_router(works.router)
api_router.include_router(playlists.router)
api_router.include_router(collections.router)
api_router.include_router(jobs.router)
api_router.include_router(provenance.router)
api_router.include_router(community.router)
api_router.include_router(engagement.router)
api_router.include_router(studio.router)
api_router.include_router(workbench.router)
api_router.include_router(challenges.router)
api_router.include_router(config.router)
api_router.include_router(config.catalog_router)
api_router.include_router(admin.router)
api_router.include_router(ops_console.router)
api_router.include_router(tenant_admin.router)
api_router.include_router(notifications.router)
api_router.include_router(copilot.router)
api_router.include_router(billing.router)
api_router.include_router(ecosystem.router)
api_router.include_router(analytics.router)
api_router.include_router(wechat_auth.router)
api_router.include_router(search.router)
api_router.include_router(releases.router)
api_router.include_router(distribution.router)
api_router.include_router(creator.router)
api_router.include_router(wallet.router)
api_router.include_router(seats.router)
api_router.include_router(sync_desk.router)
if settings.debug or settings.partner_stub_enabled:
    from app.api.routes import partner_stub

    api_router.include_router(partner_stub.router)
