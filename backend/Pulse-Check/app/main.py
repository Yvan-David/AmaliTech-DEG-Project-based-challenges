import logging
import os

import redis
from dotenv import load_dotenv
from fastapi import FastAPI

from app.services import monitor_service as svc
from app.store.redis_store import RedisStore
from app.watcher import start_watcher

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

app = FastAPI(title="Pulse-Check API — Watchdog Sentinel")


@app.on_event("startup")
async def startup() -> None:
    client = redis.from_url(REDIS_URL, decode_responses=False)
    store = RedisStore(client)
    svc.init(store)           
    start_watcher(store)    

# mount routes
from app.routes.monitors import router  # noqa: E402
app.include_router(router)
app.include_router(health_router)
