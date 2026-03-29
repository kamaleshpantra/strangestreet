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

from app.routers import auth, posts, users, feed, discover, connections, messages, zones, stories, notifications


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create all database tables on startup
    Base.metadata.create_all(bind=engine)
    print("Database tables created")

    # Ensure upload directories exist
    for d in ["app/static/uploads/posts", "app/static/uploads/avatars",
              "app/static/uploads/zones", "app/static/uploads/stories"]:
        os.makedirs(d, exist_ok=True)

    # Seed interests
    from app.seed_interests import seed_interests
    seed_interests()

    print(f"{settings.APP_NAME} is running")
    yield

application = FastAPI(
    title=settings.APP_NAME,
    lifespan=lifespan,
)

# Static files and templates
application.mount("/static", StaticFiles(directory="app/static"), name="static")

# Routers
application.include_router(feed.router)
application.include_router(auth.router)
application.include_router(posts.router)
application.include_router(users.router)
application.include_router(discover.router)
application.include_router(connections.router)
application.include_router(messages.router)
application.include_router(zones.router)
application.include_router(stories.router)
application.include_router(notifications.router)


@application.exception_handler(302)
async def redirect_handler(request: Request, exc):
    return RedirectResponse(url=exc.headers["Location"])
