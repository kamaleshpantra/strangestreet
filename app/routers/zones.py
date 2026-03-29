from fastapi import APIRouter, Depends, Request, Form, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import desc, func as sqlfunc
from database import get_db
from app.models import User, Post, Zone, ZoneMembership, Notification, Comment
from app.auth import require_login, get_current_user
import shutil, os, uuid, re

router = APIRouter(prefix="/zones", tags=["zones"])
templates = Jinja2Templates(directory="app/templates")

ZONE_UPLOAD_DIR = "app/static/uploads/zones"
ALLOWED_IMAGE = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif"}


def slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[-\s]+', '-', text)
    return text[:120]


@router.get("", response_class=HTMLResponse)
def zones_page(request: Request, q: str = "", db: Session = Depends(get_db)):
    user = require_login(request, db)

    if q:
        zones = db.query(Zone).filter(
            Zone.name.ilike(f"%{q}%")
        ).order_by(desc(Zone.member_count)).limit(50).all()
    else:
        zones = db.query(Zone).order_by(desc(Zone.member_count)).limit(50).all()

    # Trending: top zones by recent post count
    trending = db.query(Zone).order_by(desc(Zone.member_count)).limit(8).all()

    # User's zones
    my_memberships = db.query(ZoneMembership).filter(
        ZoneMembership.user_id == user.id
    ).all()
    my_zone_ids = {m.zone_id for m in my_memberships}

    return templates.TemplateResponse("zones.html", {
        "request": request, "user": user,
        "zones": zones, "trending": trending,
        "my_zone_ids": my_zone_ids, "query": q,
    })


@router.get("/create", response_class=HTMLResponse)
def create_zone_page(request: Request, db: Session = Depends(get_db)):
    user = require_login(request, db)
    return templates.TemplateResponse("zone_create.html", {
        "request": request, "user": user,
    })


@router.post("/create")
async def create_zone(
    request: Request,
    name: str = Form(...),
    description: str = Form(""),
    zone_type: str = Form("public"),
    rules: str = Form(""),
    icon_file: UploadFile = File(None),
    banner_file: UploadFile = File(None),
    db: Session = Depends(get_db),
):
    user = require_login(request, db)

    slug = slugify(name)
    if not slug:
        return templates.TemplateResponse("zone_create.html", {
            "request": request, "user": user, "error": "Invalid zone name",
        })

    # Check uniqueness
    if db.query(Zone).filter(Zone.slug == slug).first():
        return templates.TemplateResponse("zone_create.html", {
            "request": request, "user": user, "error": "A zone with this name already exists",
        })

    icon_url = None
    banner_url = None

    os.makedirs(ZONE_UPLOAD_DIR, exist_ok=True)
    for upload, prefix in [(icon_file, "icon"), (banner_file, "banner")]:
        if upload and upload.filename:
            ext = os.path.splitext(upload.filename)[1].lower()
            if ext not in ALLOWED_IMAGE:
                ext = ".jpg"
            fname = f"{prefix}_{uuid.uuid4().hex}{ext}"
            fpath = os.path.join(ZONE_UPLOAD_DIR, fname)
            with open(fpath, "wb") as f:
                shutil.copyfileobj(upload.file, f)
            url = f"/static/uploads/zones/{fname}"
            if prefix == "icon":
                icon_url = url
            else:
                banner_url = url

    zone = Zone(
        name=name, slug=slug, description=description,
        zone_type=zone_type, rules=rules,
        icon_url=icon_url, banner_url=banner_url,
        creator_id=user.id, member_count=1,
    )
    db.add(zone)
    db.flush()

    # Creator is admin
    db.add(ZoneMembership(user_id=user.id, zone_id=zone.id, role="admin"))
    db.commit()

    return RedirectResponse(f"/zones/{slug}", status_code=302)


@router.get("/{slug}", response_class=HTMLResponse)
def zone_detail(slug: str, request: Request, db: Session = Depends(get_db)):
    user = require_login(request, db)

    zone = db.query(Zone).filter(Zone.slug == slug).first()
    if not zone:
        raise HTTPException(status_code=404, detail="Zone not found")

    membership = db.query(ZoneMembership).filter(
        ZoneMembership.zone_id == zone.id,
        ZoneMembership.user_id == user.id,
    ).first()

    # Zone posts
    posts = db.query(Post).options(
        joinedload(Post.author),
        joinedload(Post.liked_by),
        joinedload(Post.comments),
        joinedload(Post.reactions),
    ).filter(
        Post.zone_id == zone.id,
        Post.is_flagged == False,
    ).order_by(desc(Post.created_at)).limit(50).all()

    # Moderators
    mods = db.query(ZoneMembership).filter(
        ZoneMembership.zone_id == zone.id,
        ZoneMembership.role.in_(["moderator", "admin"]),
    ).all()

    return templates.TemplateResponse("zone_detail.html", {
        "request": request, "user": user, "zone": zone,
        "membership": membership, "posts": posts, "mods": mods,
    })


@router.post("/{slug}/join")
def join_zone(slug: str, request: Request, db: Session = Depends(get_db)):
    user = require_login(request, db)

    zone = db.query(Zone).filter(Zone.slug == slug).first()
    if not zone:
        raise HTTPException(status_code=404)

    existing = db.query(ZoneMembership).filter(
        ZoneMembership.zone_id == zone.id,
        ZoneMembership.user_id == user.id,
    ).first()

    if existing:
        # Leave zone (unless admin)
        if existing.role == "admin":
            return JSONResponse({"joined": True, "member_count": zone.member_count,
                                 "error": "Admins cannot leave their zone"})
        db.delete(existing)
        zone.member_count = max(0, zone.member_count - 1)
        db.commit()
        return JSONResponse({"joined": False, "member_count": zone.member_count})
    else:
        # Join zone
        db.add(ZoneMembership(user_id=user.id, zone_id=zone.id, role="member"))
        zone.member_count += 1
        db.commit()
        return JSONResponse({"joined": True, "member_count": zone.member_count})


@router.post("/{slug}/post")
async def create_zone_post(
    slug: str, request: Request,
    content: str = Form(...),
    media: UploadFile = File(None),
    db: Session = Depends(get_db),
):
    user = require_login(request, db)

    zone = db.query(Zone).filter(Zone.slug == slug).first()
    if not zone:
        raise HTTPException(status_code=404)

    # Must be member
    membership = db.query(ZoneMembership).filter(
        ZoneMembership.zone_id == zone.id,
        ZoneMembership.user_id == user.id,
    ).first()
    if not membership:
        raise HTTPException(status_code=403, detail="Must join zone to post")

    media_url = None
    media_type = None
    UPLOAD_DIR = "app/static/uploads/posts"
    VIDEO_EXT = {".mp4", ".webm", ".ogg", ".mov", ".avi", ".mkv"}

    if media and media.filename:
        ext = os.path.splitext(media.filename)[1].lower()
        fname = f"{uuid.uuid4().hex}{ext}"
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        fpath = os.path.join(UPLOAD_DIR, fname)
        with open(fpath, "wb") as f:
            shutil.copyfileobj(media.file, f)
        media_url = f"/static/uploads/posts/{fname}"
        media_type = "video" if ext in VIDEO_EXT else "image"

    post = Post(
        content=content, user_id=user.id, zone_id=zone.id,
        image_url=media_url, media_type=media_type,
        category=zone.name,
    )
    db.add(post)
    db.commit()

    return RedirectResponse(f"/zones/{slug}", status_code=302)


@router.post("/{slug}/moderate/{post_id}/{action}")
def moderate_post(
    slug: str, post_id: int, action: str,
    request: Request, db: Session = Depends(get_db),
):
    user = require_login(request, db)

    zone = db.query(Zone).filter(Zone.slug == slug).first()
    if not zone:
        raise HTTPException(status_code=404)

    membership = db.query(ZoneMembership).filter(
        ZoneMembership.zone_id == zone.id,
        ZoneMembership.user_id == user.id,
        ZoneMembership.role.in_(["moderator", "admin"]),
    ).first()
    if not membership:
        raise HTTPException(status_code=403)

    post = db.query(Post).filter(Post.id == post_id, Post.zone_id == zone.id).first()
    if not post:
        raise HTTPException(status_code=404)

    if action == "pin":
        post.is_pinned = not post.is_pinned
    elif action == "remove":
        post.is_flagged = True
        post.flag_reason = f"Removed by moderator {user.username}"
    elif action == "delete":
        db.delete(post)

    db.commit()
    return JSONResponse({"status": "ok", "action": action})
