from fastapi import APIRouter
from fastapi.responses import PlainTextResponse


auth_router = APIRouter(prefix="/api/auth")


@auth_router.get("/", response_class=PlainTextResponse)
async def auth_home() -> str:
    return "auth Home"