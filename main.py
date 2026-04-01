from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
from contextlib import asynccontextmanager
from database import engine, Base
from config import settings
import os

# Import all models so SQLAlchemy creates tables
import app.models  # noqa

from app.routers import auth, posts, users, feed, discover, connections, messages, zones, stories, notifications, admin, search


from app.logging_config import logger

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create all database tables on startup (legacy, Alembic will handle this in prod)
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables verified/created")

    # Ensure upload directories exist
    for d in ["app/static/uploads/posts", "app/static/uploads/avatars",
              "app/static/uploads/zones", "app/static/uploads/stories"]:
        os.makedirs(d, exist_ok=True)

    # Seed interests
    from app.seed_interests import seed_interests
    seed_interests()

    # Start ML pipeline scheduler
    try:
        from ml.scheduler import start_scheduler
        start_scheduler()
    except Exception as e:
        print(f"Scheduler start skipped: {e}")

    print(f"{settings.APP_NAME} is running")
    yield

app = FastAPI(
    title=settings.APP_NAME,
    lifespan=lifespan,
)

# Static files and templates
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Routers
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


@app.exception_handler(302)
async def redirect_handler(request: Request, exc):
    return RedirectResponse(url=exc.headers["Location"])
