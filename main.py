import uvicorn

from app import create_app

api_application = create_app()

if __name__ == "__main__":
    uvicorn.run(
        "app:create_app",
        factory=True,
        host="127.0.0.1",
        port=5000,
        reload=True,
    )