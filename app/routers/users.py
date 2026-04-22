from fastapi import APIRouter, Depends, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import desc, or_
from database import get_db
from app.models import User, Post, Interest, Notification, Bookmark, ZoneMembership
from app.auth import get_current_user, require_login
from app.constants import UPLOAD_DIR_AVATARS as AVATAR_DIR, ALLOWED_IMAGE_EXT as ALLOWED_IMAGE
import shutil, os
from fastapi import UploadFile, File
import uuid

router = APIRouter(prefix="/users", tags=["users"])
templates = Jinja2Templates(directory="app/templates")

from pydantic import BaseModel

class PublicKeySync(BaseModel):
    public_key: str

@router.post("/me/public-key")
def sync_public_key(payload: PublicKeySync, request: Request, db: Session = Depends(get_db)):
    user = require_login(request, db)
    user.public_key = payload.public_key
    db.commit()
    return {"status": "synced"}




@router.get("/bookmarks", response_class=HTMLResponse)
def bookmarks_page(request: Request, db: Session = Depends(get_db)):
    user = require_login(request, db)
    bookmarks = db.query(Bookmark).filter(
        Bookmark.user_id == user.id,
    ).order_by(desc(Bookmark.created_at)).all()

    posts = [b.post for b in bookmarks if b.post]

    return templates.TemplateResponse("bookmarks.html", {
        "request": request, "user": user, "posts": posts,
    })


@router.get("/{username}", response_class=HTMLResponse)
def profile(username: str, request: Request, db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse("/auth/login", status_code=302)

    profile_user = db.query(User).filter(User.username == username).first()
    if not profile_user:
        raise HTTPException(status_code=404, detail="User not found")

    posts = db.query(Post).options(
        joinedload(Post.liked_by),
        joinedload(Post.comments),
        joinedload(Post.reactions),
    ).filter(
        Post.user_id == profile_user.id
    ).order_by(desc(Post.created_at)).limit(20).all()

    is_following = any(u.id == profile_user.id for u in current_user.following)

    # User's zones
    memberships = db.query(ZoneMembership).filter(
        ZoneMembership.user_id == profile_user.id,
    ).all()

    return templates.TemplateResponse("profile.html", {
        "request":        request,
        "user":           current_user,
        "profile_user":   profile_user,
        "posts":          posts,
        "is_following":   is_following,
        "follower_count": len(profile_user.followers),
        "following_count":len(profile_user.following),
        "post_count":     len(posts),
        "memberships":    memberships,
        "followers_list": profile_user.followers,
        "following_list": profile_user.following,
    })


@router.post("/{username}/follow")
def follow_user(username: str, request: Request, db: Session = Depends(get_db)):
    current_user = require_login(request, db)
    target = db.query(User).filter(User.username == username).first()
    if not target or target.id == current_user.id:
        raise HTTPException(status_code=400)

    is_following = any(u.id == target.id for u in current_user.following)
    if is_following:
        current_user.following.remove(target)
    else:
        current_user.following.append(target)
        db.add(Notification(
            user_id=target.id, actor_id=current_user.id,
            type="follow", reference_id=current_user.id, reference_type="user",
            message=f"{current_user.display_name} started following you",
        ))
    db.commit()
    return JSONResponse({
        "following": not is_following,
        "follower_count": len(target.followers),
    })


@router.get("/{username}/edit", response_class=HTMLResponse)
def edit_profile_page(username: str, request: Request, db: Session = Depends(get_db)):
    user = require_login(request, db)
    if user.username != username:
        raise HTTPException(status_code=403)

    # Get interests grouped by category
    interests = db.query(Interest).order_by(Interest.category, Interest.name).all()
    categories = {}
    for i in interests:
        if i.category not in categories:
            categories[i.category] = []
        categories[i.category].append(i)

    user_interest_ids = {i.id for i in user.interests}

    return templates.TemplateResponse("edit_profile.html", {
        "request": request, "user": user,
        "categories": categories,
        "user_interest_ids": user_interest_ids,
    })


@router.post("/{username}/edit")
async def edit_profile(
    username:            str,
    request:             Request,
    display_name:        str        = Form(""),
    bio:                 str        = Form(""),
    relationship_status: str        = Form(""),
    alias_name:          str        = Form(""),
    alias_bio:           str        = Form(""),
    alias_relationship_status: str  = Form(""),
    interest_ids:        str        = Form(""),
    remove_avatar:       str        = Form("false"),
    avatar_file:         UploadFile = File(None),
    db:                  Session    = Depends(get_db),
):
    user = require_login(request, db)
    if user.username != username:
        raise HTTPException(status_code=403)

    user.display_name        = display_name or user.display_name
    user.bio                 = bio
    user.relationship_status = relationship_status or None
    user.alias_name          = alias_name or user.alias_name
    user.alias_bio           = alias_bio or None
    user.alias_relationship_status = alias_relationship_status or None

    # Update interests
    if interest_ids:
        ids = [int(x) for x in interest_ids.split(",") if x.strip().isdigit()]
        interests = db.query(Interest).filter(Interest.id.in_(ids)).all()
        user.interests = interests
    else:
        user.interests = []

    # Handle avatar removal
    if remove_avatar == "true":
        if user.avatar_url:
            if user.avatar_url.startswith("/static/uploads/avatars/"):
                old_path = user.avatar_url.lstrip("/")
                if os.path.exists(old_path):
                    try:
                        os.remove(old_path)
                    except Exception:
                        pass
            elif "res.cloudinary.com" in user.avatar_url:
                from app.services.cloudinary_service import CloudinaryService
                public_id = CloudinaryService.get_public_id(user.avatar_url)
                if public_id:
                    CloudinaryService.delete_image(public_id)
            user.avatar_url = None

    # Handle avatar upload
    if avatar_file and avatar_file.filename:
        from app.utils import compress_image
        from config import settings
        
        # compress_image now returns a URL (Cloudinary) or a filename (local)
        folder = "strangestreet/avatars"
        img_result = compress_image(avatar_file, AVATAR_DIR, prefix="av_", max_size=(600, 600), folder=folder)
        
        if img_result:
            # Clean up old avatar
            if user.avatar_url:
                if user.avatar_url.startswith("/static/uploads/avatars/"):
                    old_path = user.avatar_url.lstrip("/")
                    if os.path.exists(old_path):
                        os.remove(old_path)
                elif "res.cloudinary.com" in user.avatar_url:
                    from app.services.cloudinary_service import CloudinaryService
                    public_id = CloudinaryService.get_public_id(user.avatar_url)
                    if public_id:
                        CloudinaryService.delete_image(public_id)

            if img_result.startswith("http"):
                user.avatar_url = img_result
            else:
                user.avatar_url = f"/static/uploads/avatars/{img_result}"

    db.commit()
    return RedirectResponse(f"/users/{username}", status_code=302)
