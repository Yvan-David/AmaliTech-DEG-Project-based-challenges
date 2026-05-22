import logging

from fastapi import FastAPI

from app.routes.monitors import router as monitors_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

app = FastAPI(
    title="Pulse Check API",
    description=(
        "Dead Man's Switch API for critical infrastructure monitoring. "
        "Devices register a monitor with a countdown timer; if they stop sending "
        "heartbeats before the timer expires, an alert is automatically fired."
    ),
    version="1.0.0",
    contact={"name": "CritMon Servers Inc.", "email": "support@critmon.com"},
)

app.include_router(monitors_router)


@app.get("/health", tags=["Health"], summary="Health check")
async def health():
    """Lightweight liveness probe for load balancers and Docker HEALTHCHECK."""
    return {"status": "ok"}
