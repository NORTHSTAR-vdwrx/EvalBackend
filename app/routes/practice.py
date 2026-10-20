from fastapi import APIRouter
from fastapi.responses import JSONResponse

practice_router = APIRouter(prefix="/api/practice")


@practice_router.get("/student", response_class=JSONResponse)
async def student() -> JSONResponse:
    return JSONResponse(content={"key":"text"})
