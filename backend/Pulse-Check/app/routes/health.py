from fastapi import APIRouter
from fastapi.responses import JSONResponse

health_router = APIRouter(tags=["System"])


@health_router.get("/health")
async def health():
    return {"status": "ok"}


@health_router.get("/")
async def root():
    return JSONResponse({
        "system": "Pulse-Check API — Watchdog Sentinel",
        "description": (
            "A Dead Man's Switch API for monitoring remote devices. "
            "Devices register a countdown timer and must send periodic heartbeats. "
            "If a device goes silent, an alert email is fired automatically."
        ),
        "version": "1.0.0",
        "status": "operational",
        "docs": "/docs",
        "endpoints": {
            "register_monitor":  "POST   /monitors",
            "heartbeat":         "POST   /monitors/{id}/heartbeat",
            "pause":             "POST   /monitors/{id}/pause",
            "get_monitor":       "GET    /monitors/{id}",
            "list_monitors":     "GET    /monitors",
            "delete_monitor":    "DELETE /monitors/{id}",
        },
        "tip": "Visit /docs for the full interactive API reference.",
    })
