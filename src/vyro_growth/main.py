from fastapi import FastAPI

from vyro_growth.config import get_settings

settings = get_settings()
app = FastAPI(title=settings.app_name, version="0.1.0")


@app.get("/health", tags=["system"])
def health() -> dict[str, str | bool]:
    return {
        "status": "ok",
        "environment": settings.environment,
        "outbound_enabled": settings.outbound_enabled,
    }
