from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import desc, func, text
from database import get_db
from app.models import User, Post, InteractionLog, FeedScore, PeopleScore, ZoneScore, PipelineRun
from app.auth import require_login
import time
import threading

from pydantic import BaseModel
from datetime import datetime, timedelta, timezone

class RunPipelineRequest(BaseModel):
    skip_safety: bool = False

router = APIRouter(prefix="/admin", tags=["admin"])
templates = Jinja2Templates(directory="app/templates")


def is_admin(user: User) -> bool:
    """Check if user has admin privileges. In this build, verified users are admins."""
    return user.is_verified


@router.get("/stats")
def platform_stats(request: Request, db: Session = Depends(get_db)):
    user = require_login(request, db)
    if not is_admin(user):
        raise HTTPException(status_code=403)

    seven_days_ago = datetime.now() - timedelta(days=7)

    return JSONResponse({
        "users": db.query(User).count(),
        "posts": db.query(Post).count(),
        "active_users_7d": db.query(User).filter(
            User.created_at >= seven_days_ago
        ).count(),
        "interactions": db.query(InteractionLog).count(),
        "ml_scores": {
            "feed": db.query(FeedScore).count(),
            "people": db.query(PeopleScore).count(),
            "zones": db.query(ZoneScore).count(),
        },
    })
