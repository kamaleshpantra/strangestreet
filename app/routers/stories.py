from fastapi import APIRouter, Depends, Request, Form, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import desc
from database import get_db
from app.models import Story, StoryView, User
from app.auth import require_login
from datetime import datetime, timedelta, timezone
import shutil, os, uuid

router = APIRouter(prefix="/stories", tags=["stories"])
templates = Jinja2Templates(directory="app/templates")

STORY_DIR = "app/static/uploads/stories"
VIDEO_EXT = {".mp4", ".webm", ".ogg", ".mov"}
ALLOWED = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".mp4", ".webm", ".ogg", ".mov"}


@router.get("/bar", response_class=HTMLResponse)
def story_bar(request: Request, db: Session = Depends(get_db)):
    """Returns the story bar HTML fragment (for inclusion in feed)."""
    from app.auth import get_current_user
    user = get_current_user(request, db)
    if not user:
        return HTMLResponse("")

    now = datetime.now(timezone.utc)

    # Users with active stories (following + self)
    following_ids = [u.id for u in user.following] + [user.id]
    active_stories = db.query(Story).filter(
        Story.user_id.in_(following_ids),
        Story.expires_at > now,
    ).order_by(desc(Story.created_at)).all()

    # Group by user
    story_users = {}
    for story in active_stories:
        if story.user_id not in story_users:
            viewed = any(v.viewer_id == user.id for v in story.views)
            story_users[story.user_id] = {
                "user": story.author,
                "stories": [],
                "all_viewed": viewed,
            }
        story_users[story.user_id]["stories"].append(story)
        if not any(v.viewer_id == user.id for v in story.views):
            story_users[story.user_id]["all_viewed"] = False

    # My story first, then unviewed, then viewed
    ordered = []
    if user.id in story_users:
        ordered.append(story_users.pop(user.id))
    unviewed = [v for v in story_users.values() if not v["all_viewed"]]
    viewed = [v for v in story_users.values() if v["all_viewed"]]
    ordered.extend(unviewed + viewed)

    return templates.TemplateResponse("story_bar.html", {
        "request": request, "user": user, "story_users": ordered,
        "has_my_story": any(s.user_id == user.id for s in active_stories),
    })


@router.post("/create")
async def create_story(
    request: Request,
    caption: str = Form(""),
    media: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    user = require_login(request, db)

    if not media or not media.filename:
        return RedirectResponse("/", status_code=302)

    ext = os.path.splitext(media.filename)[1].lower()
    if ext not in ALLOWED:
        ext = ".jpg"

    fname = f"{uuid.uuid4().hex}{ext}"
    os.makedirs(STORY_DIR, exist_ok=True)
    fpath = os.path.join(STORY_DIR, fname)
    with open(fpath, "wb") as f:
        shutil.copyfileobj(media.file, f)

    media_url = f"/static/uploads/stories/{fname}"
    media_type = "video" if ext in VIDEO_EXT else "image"

    story = Story(
        user_id=user.id,
        media_url=media_url,
        media_type=media_type,
        caption=caption[:200] if caption else None,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
    )
    db.add(story)
    db.commit()

    return RedirectResponse("/", status_code=302)


@router.get("/{user_id}", response_class=HTMLResponse)
def view_stories(user_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_login(request, db)

    now = datetime.now(timezone.utc)
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404)

    stories = db.query(Story).filter(
        Story.user_id == user_id,
        Story.expires_at > now,
    ).order_by(Story.created_at).all()

    if not stories:
        return RedirectResponse("/", status_code=302)

    # Build story data with view status
    story_data = []
    for s in stories:
        viewed = any(v.viewer_id == user.id for v in s.views)
        story_data.append({"story": s, "viewed": viewed})

    return templates.TemplateResponse("stories.html", {
        "request": request, "user": user,
        "target": target, "stories": story_data,
    })


@router.post("/{story_id}/view")
def mark_viewed(story_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_login(request, db)

    story = db.query(Story).filter(Story.id == story_id).first()
    if not story:
        return JSONResponse({"ok": False})

    existing = db.query(StoryView).filter(
        StoryView.story_id == story_id,
        StoryView.viewer_id == user.id,
    ).first()

    if not existing:
        db.add(StoryView(story_id=story_id, viewer_id=user.id))
        db.commit()

    return JSONResponse({"ok": True})
