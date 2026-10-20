from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

admin_router = APIRouter(prefix="/admin")


@admin_router.get("/settings", response_class=PlainTextResponse)
async def admin_settings() -> str:
    return "admin settings page"