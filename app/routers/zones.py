from fastapi import APIRouter, Depends, Request, Form, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import desc, func as sqlfunc
from database import get_db
from app.models import User, Post, Zone, ZoneMembership, Notification, Comment, ZoneFlair, ZoneBan
from app.auth import require_login, get_current_user
from app.constants import UPLOAD_DIR_ZONES as ZONE_UPLOAD_DIR, ALLOWED_IMAGE_EXT as ALLOWED_IMAGE, ALLOWED_VIDEO_EXT as VIDEO_EXT
import shutil, os, uuid, re

router = APIRouter(prefix="/zones", tags=["zones"])
templates = Jinja2Templates(directory="app/templates")


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

    # ML-recommended zones
    from app.models import ZoneScore
    recommended_zones = []
    zone_scores = db.query(ZoneScore).filter(
        ZoneScore.user_id == user.id,
        ZoneScore.zone_id.notin_(my_zone_ids) if my_zone_ids else True,
    ).order_by(desc(ZoneScore.score)).limit(6).all()
    if zone_scores:
        rec_zone_ids = [zs.zone_id for zs in zone_scores]
        rec_zones_by_id = {
            z.id: z for z in db.query(Zone).filter(Zone.id.in_(rec_zone_ids)).all()
        }
        recommended_zones = [rec_zones_by_id[zid] for zid in rec_zone_ids if zid in rec_zones_by_id]

    return templates.TemplateResponse("zones.html", {
        "request": request, "user": user,
        "zones": zones, "trending": trending,
        "recommended_zones": recommended_zones,
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

    from app.utils import compress_image
    from app.services.cloudinary_service import CloudinaryService
    from config import settings
    
    # Process Icon
    if icon_file and icon_file.filename:
        res = compress_image(icon_file, ZONE_UPLOAD_DIR, prefix="icon_", max_size=(400, 400), folder="strangestreet/zones")
        if res:
            icon_url = res if res.startswith("http") else f"/static/uploads/zones/{res}"
        
    # Process Banner
    if banner_file and banner_file.filename:
        res = compress_image(banner_file, ZONE_UPLOAD_DIR, prefix="banner_", max_size=(1600, 800), folder="strangestreet/zones")
        if res:
            banner_url = res if res.startswith("http") else f"/static/uploads/zones/{res}"

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

    # Check if user is banned
    is_admin = False
    is_mod = False
    
    if user:
        ban = db.query(ZoneBan).filter(ZoneBan.zone_id == zone.id, ZoneBan.user_id == user.id).first()
        if ban:
            import html as html_mod
            safe_reason = html_mod.escape(ban.reason or 'No reason provided')
            return HTMLResponse(
                f"<div style='padding:50px;text-align:center;font-family:Inter,sans-serif;color:#f8fafc;background:#050505;min-height:100vh;display:flex;align-items:center;justify-content:center;'>"
                f"<div><h2 style='color:#e11d48;'>You have been banned from this Zone</h2>"
                f"<p style='color:#94a3b8;margin-top:12px;'>Reason: {safe_reason}</p>"
                f"<a href='/zones' style='color:#f43f5e;margin-top:20px;display:inline-block;'>Back to Zones</a></div></div>",
                status_code=403,
            )
            
        membership = db.query(ZoneMembership).filter(
            ZoneMembership.zone_id == zone.id,
            ZoneMembership.user_id == user.id,
        ).first()
        
        if membership:
            if membership.role == 'admin': is_admin = True
            elif membership.role == 'moderator': is_mod = True
    else:
        membership = None

    flairs = db.query(ZoneFlair).filter(ZoneFlair.zone_id == zone.id).all()

    # Zone posts, order by pinned then creation
    posts_query = db.query(Post).options(
        joinedload(Post.author),
        joinedload(Post.liked_by),
        joinedload(Post.comments),
        joinedload(Post.reactions),
        joinedload(Post.flair),
    ).filter(
        Post.zone_id == zone.id,
        Post.is_flagged == False,
    )
    
    # Filter by flair if requested
    flair_filter = request.query_params.get("flair")
    if flair_filter and flair_filter.isdigit():
        posts_query = posts_query.filter(Post.flair_id == int(flair_filter))

    posts = posts_query.order_by(desc(Post.is_pinned), desc(Post.created_at)).limit(50).all()

    # Moderators
    mods = db.query(ZoneMembership).filter(
        ZoneMembership.zone_id == zone.id,
        ZoneMembership.role.in_(["moderator", "admin"]),
    ).all()

    return templates.TemplateResponse("zone_detail.html", {
        "request": request, "user": user, "zone": zone,
        "membership": membership, "posts": posts, "mods": mods,
        "flairs": flairs, "is_admin": is_admin, "is_mod": is_mod,
        "active_flair": flair_filter,
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

    # Flair enforcement
    flair_id_int = None
    flairs_exist = db.query(ZoneFlair).filter(ZoneFlair.zone_id == zone.id).count() > 0
    if flairs_exist:
        raw_flair = request.query_params.get("flair_id") or (await request.form()).get("flair_id")
        if not raw_flair:
            return RedirectResponse(f"/zones/{slug}?error=A flair is required to post here", status_code=302)
        flair_id_int = int(raw_flair)

    media_url = None
    media_type = None
    UPLOAD_DIR = "app/static/uploads/posts"

    if media and media.filename:
        from app.utils import compress_image
        from config import settings
        from app.services.cloudinary_service import CloudinaryService
        
        ext = os.path.splitext(media.filename)[1].lower()
        is_video = ext in VIDEO_EXT
        
        # 1. Try Cloudinary
        if settings.CLOUDINARY_CLOUD_NAME:
            media_url = CloudinaryService.upload_image(media.file, folder="strangestreet/posts")
            if media_url:
                media_type = "video" if is_video else "image"
        
        # 2. Local Fallback
        if not media_url:
            UPLOAD_DIR = "app/static/uploads/posts"
            if is_video:
                fname = f"{uuid.uuid4().hex}{ext}"
                os.makedirs(UPLOAD_DIR, exist_ok=True)
                fpath = os.path.join(UPLOAD_DIR, fname)
                with open(fpath, "wb") as f:
                    shutil.copyfileobj(media.file, f)
                media_url = f"/static/uploads/posts/{fname}"
            else:
                res = compress_image(media, UPLOAD_DIR, max_size=(1600, 1600))
                if res:
                    media_url = res if res.startswith("http") else f"/static/uploads/posts/{res}"
            
            media_type = "video" if is_video else "image"

    post = Post(
        content=content, user_id=user.id, zone_id=zone.id,
        image_url=media_url, media_type=media_type,
        category=zone.name, flair_id=flair_id_int,
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


@router.post("/{slug}/flair")
def create_flair(
    slug: str, request: Request, name: str = Form(...), color: str = Form("#4B5563"),
    db: Session = Depends(get_db),
):
    user = require_login(request, db)
    zone = db.query(Zone).filter(Zone.slug == slug).first()
    if not zone: raise HTTPException(status_code=404)
    
    membership = db.query(ZoneMembership).filter(
        ZoneMembership.zone_id == zone.id, ZoneMembership.user_id == user.id,
        ZoneMembership.role.in_(["moderator", "admin"])
    ).first()
    if not membership: raise HTTPException(status_code=403)
    
    flair = ZoneFlair(zone_id=zone.id, name=name[:50], color_hex=color[:7])
    db.add(flair)
    db.commit()
    return RedirectResponse(f"/zones/{slug}", status_code=302)


@router.post("/{slug}/ban/{banned_user_id}")
def ban_user(
    slug: str, banned_user_id: int, request: Request,
    reason: str = Form("Violated zone rules"), db: Session = Depends(get_db),
):
    user = require_login(request, db)
    zone = db.query(Zone).filter(Zone.slug == slug).first()
    if not zone: raise HTTPException(status_code=404)
    
    membership = db.query(ZoneMembership).filter(
        ZoneMembership.zone_id == zone.id, ZoneMembership.user_id == user.id,
        ZoneMembership.role.in_(["moderator", "admin"])
    ).first()
    if not membership: raise HTTPException(status_code=403)
    
    db.add(ZoneBan(zone_id=zone.id, user_id=banned_user_id, reason=reason))
    # Also kick them from the membership table
    db.query(ZoneMembership).filter(ZoneMembership.zone_id == zone.id, ZoneMembership.user_id == banned_user_id).delete()
    db.commit()
    return RedirectResponse(f"/zones/{slug}", status_code=302)
