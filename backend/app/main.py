import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from .config import get_settings
from .db import SessionLocal, init_db
from .routers import admin, auth, bookings, chargers, communities, community, me, payments, receipts
from .services import booking_logic

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("chargeshare")
LEGAL_DIR = Path(__file__).resolve().parent.parent / "legal"


def _sweep_once() -> dict:
    with SessionLocal() as db:
        return booking_logic.sweep(db)


async def _sweeper():
    """Every minute: release unpaid slots, expire unanswered requests, auto-complete finished sessions."""
    while True:
        try:
            counts = await asyncio.to_thread(_sweep_once)
            if any(counts.values()):
                log.info("sweep: %s", counts)
        except Exception:  # keep the loop alive no matter what
            log.exception("sweep failed")
        await asyncio.sleep(60)


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    if s.is_production and s.jwt_secret == "change-me-in-production":
        raise RuntimeError("Set JWT_SECRET before running in production")
    init_db()
    task = asyncio.create_task(_sweeper())
    yield
    task.cancel()


settings = get_settings()
app = FastAPI(title=f"{settings.app_name} API", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
    allow_methods=["*"],
    allow_headers=["*"],
)

for r in (
    auth.router, me.router, chargers.router, bookings.router, payments.router, community.router,
    communities.router, receipts.router, admin.router,
):
    app.include_router(r)

if settings.storage_backend == "local":
    public_dir = Path(settings.local_upload_dir) / "public"
    public_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/media", StaticFiles(directory=public_dir), name="media")


@app.get("/health")
def health():
    return {"ok": True, "payments": settings.payment_provider, "otp": settings.otp_provider}


def _legal(name: str) -> HTMLResponse:
    path = LEGAL_DIR / f"{name}.html"
    return HTMLResponse(path.read_text(encoding="utf-8") if path.exists() else "<h1>Coming soon</h1>")


@app.get("/legal/privacy", response_class=HTMLResponse, include_in_schema=False)
def privacy():
    return _legal("privacy")


@app.get("/legal/terms", response_class=HTMLResponse, include_in_schema=False)
def terms():
    return _legal("terms")


@app.get("/legal/delete-account", response_class=HTMLResponse, include_in_schema=False)
def delete_account_info():
    return _legal("delete-account")


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def home():
    return f"<h2>{settings.app_name} API is running</h2><p>Docs: <a href='/docs'>/docs</a></p>"
