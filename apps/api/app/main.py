from fastapi import FastAPI

from app.config import settings

app = FastAPI(title="TradeTwin API", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": settings.service_name}
