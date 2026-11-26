"""HTTP API routes for system announcements."""

from fastapi import APIRouter
from starlette.responses import JSONResponse

from .announcements import AnnouncementStore


def init_announcement_routes(store: AnnouncementStore) -> APIRouter:
    """Create and return routes exposing active system announcements."""
    router = APIRouter()

    @router.get("/api/announcements")
    async def get_announcements() -> JSONResponse:
        return JSONResponse(
            {"announcements": store.list_active()},
            headers={"Cache-Control": "no-store"},
        )

    return router
