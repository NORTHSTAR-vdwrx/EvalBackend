from fastapi import APIRouter
from fastapi.responses import JSONResponse, PlainTextResponse

home_router = APIRouter()


@home_router.get("/", response_class=PlainTextResponse)
async def home() -> str:
    return "ok"

@home_router.get("/about", response_class=PlainTextResponse)
async def about() -> str:
    return "Northstar Eval"

@home_router.get("/api/health", response_class=JSONResponse)
async def health() -> JSONResponse:
    return JSONResponse(content={"status": "ok"})
