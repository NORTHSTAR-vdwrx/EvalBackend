from fastapi import APIRouter
from fastapi.responses import JSONResponse

practice_router = APIRouter(prefix="/api/practice")


@practice_router.get("/student", response_class=JSONResponse)
async def student() -> JSONResponse:
    return JSONResponse(content={"key":"text"})
@practice_router.get("/hello/{name}")
async def hello(name: str) -> JSONResponse: 
    return JSONResponse({"message": "hello {name}!"})
@practice_router.get("/greet")
async def greet(name: str = "stranger") -> JSONResponse:
    return JSONResponse({"message": "Hey there {name}!"})
