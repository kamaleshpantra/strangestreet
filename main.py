import os
# Force Machine Learning libraries to use minimum memory & threads (Crucial for 512MB limit)
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["VECLIB_MAXIMUM_THREADS"] = "1"
os.environ["NUMEXPR_NUM_THREADS"] = "1"

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse
import traceback
from contextlib import asynccontextmanager
from database import engine, Base, SessionLocal
from config import settings

# Import all models so SQLAlchemy creates tables
import app.models  # noqa

from app.routers import auth, posts, users, feed, discover, connections, messages, zones, stories, notifications, admin, search, economy

from app.logging_config import logger

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Run pending Alembic migrations on every startup ──────────────────────
    try:
        from alembic.config import Config
        from alembic import command
        alembic_cfg = Config("alembic.ini")
        command.upgrade(alembic_cfg, "head")
        logger.info("Alembic migrations applied successfully")
    except Exception as e:
        logger.error(f"Alembic migration failed: {e}")

    # Create any tables not yet tracked by Alembic (safe no-op if already exists)
    Base.metadata.create_all(bind=engine)

    logger.info("Database tables verified/created")

    # Ensure upload directories exist
    for d in ["app/static/uploads/posts", "app/static/uploads/avatars",
              "app/static/uploads/zones", "app/static/uploads/stories",
              "app/static/uploads/messages"]:
        os.makedirs(d, exist_ok=True)

    # Seed interests
    from app.seed_interests import seed_interests
    seed_interests()

    # Initialize Bloom Filters
    from app.services.bloom_service import bloom_service
    db = SessionLocal()
    try:
        bloom_service.init_filters(db)
    except Exception as e:
        logger.error(f"Failed to init bloom filters: {e}")
    finally:
        db.close()

    # Start ML pipeline scheduler
    try:
        from ml.scheduler import start_scheduler
        start_scheduler()
    except Exception as e:
        logger.warning(f"Scheduler start skipped: {e}")

    logger.info(f"{settings.APP_NAME} is running")
    yield

app = FastAPI(
    title=settings.APP_NAME,
    lifespan=lifespan,
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url=None,
)

# ── Middleware ─────────────────────────────────────────────────────────────────
from app.middleware import RateLimitMiddleware, SecurityHeadersMiddleware

app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    RateLimitMiddleware,
    requests_per_minute=120,
    burst_paths={
        "/auth/login": 10,      # 10 login attempts per minute
        "/auth/register": 5,    # 5 registration attempts per minute
        "/search": 30,          # 30 searches per minute
    },
)

# Static files and templates
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# ── Health Check ──────────────────────────────────────────────────────────────
@app.get("/health", tags=["system"])
def health_check():
    """Health check endpoint for Render/Docker monitoring."""
    return JSONResponse({"status": "ok", "app": settings.APP_NAME})


# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(feed.router)
app.include_router(auth.router)
app.include_router(posts.router)
app.include_router(users.router)
app.include_router(discover.router)
app.include_router(connections.router)
app.include_router(messages.router)
app.include_router(zones.router)
app.include_router(stories.router)
app.include_router(notifications.router)
app.include_router(search.router)
app.include_router(admin.router)
app.include_router(economy.router)


# ── Error Handlers ────────────────────────────────────────────────────────────
@app.exception_handler(302)
async def redirect_handler(request: Request, exc):
    return RedirectResponse(url=exc.headers["Location"])


@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    """Return a user-friendly 404 page."""
    return HTMLResponse(
        content="""
        <html><head><title>404 — Not Found</title>
        <style>body{background:#050505;color:#f8fafc;font-family:'Inter',sans-serif;display:flex;
        align-items:center;justify-content:center;height:100vh;margin:0;text-align:center;}
        .c{max-width:400px}.t{font-size:64px;font-weight:800;color:#e11d48;margin-bottom:8px}
        .s{font-size:16px;color:#94a3b8;margin-bottom:24px}
        a{color:#f43f5e;text-decoration:none;font-weight:600}a:hover{opacity:.8}</style></head>
        <body><div class="c"><div class="t">404</div><div class="s">This street doesn't exist.</div>
        <a href="/">← Back to Strange Street</a></div></body></html>
        """,
        status_code=404,
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """
    In production: return a generic error page (never expose internals).
    In debug mode: return the full traceback for development.
    """
    if settings.DEBUG:
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        logger.error(f"Unhandled exception: {tb}")
        return HTMLResponse(
            content=f"<pre style='background:#111;color:#f87171;padding:20px;font-family:monospace;'>{tb}</pre>",
            status_code=500,
        )

    # Production: log the error, show generic message
    logger.error(f"Unhandled exception on {request.url.path}: {exc}", exc_info=True)
    return HTMLResponse(
        content="""
        <html><head><title>500 — Server Error</title>
        <style>body{background:#050505;color:#f8fafc;font-family:'Inter',sans-serif;display:flex;
        align-items:center;justify-content:center;height:100vh;margin:0;text-align:center;}
        .c{max-width:420px}.t{font-size:64px;font-weight:800;color:#e11d48;margin-bottom:8px}
        .s{font-size:16px;color:#94a3b8;margin-bottom:24px}
        a{color:#f43f5e;text-decoration:none;font-weight:600}a:hover{opacity:.8}</style></head>
        <body><div class="c"><div class="t">500</div>
        <div class="s">Something went wrong. We're on it.</div>
        <a href="/">← Back to Strange Street</a></div></body></html>
        """,
        status_code=500,
    )
