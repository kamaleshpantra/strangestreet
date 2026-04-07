from fastapi import APIRouter, Depends, Request, Form, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import desc
from database import get_db
from app.models import Post, Comment, InteractionLog, User, Reaction, Bookmark, Poll, PollOption, PollVote, Notification
from app.auth import get_current_user, require_login
import shutil, os, uuid

router = APIRouter(prefix="/posts", tags=["posts"])
templates = Jinja2Templates(directory="app/templates")

UPLOAD_DIR = "app/static/uploads/posts"
ALLOWED_EXT = {
    ".jpg",".jpeg",".png",".gif",".webp",".avif",".bmp",".tiff",".svg",".ico",
    ".mp4",".webm",".ogg",".mov",".avi",".mkv",".m4v",".3gp",".flv",".wmv",
}
VIDEO_EXT = {".mp4",".webm",".ogg",".mov",".avi",".mkv",".m4v",".3gp",".flv",".wmv"}
CATEGORIES = ["general","technology","sports","news","science","gaming","food","travel","music","art"]
ACTION_WEIGHTS = {"view":0.1,"like":1.0,"comment":2.0,"share":3.0,"skip":-0.5}

REACTION_EMOJIS = {
    "fire": "🔥", "love": "❤️", "laugh": "😂",
    "mind_blown": "🤯", "clap": "👏", "dead": "💀",
}


def log_interaction(db, user_id, post_id, action):
    db.add(InteractionLog(
        user_id=user_id, post_id=post_id,
        action=action, weight=ACTION_WEIGHTS.get(action, 0.0),
    ))
    db.commit()


@router.get("/create", response_class=HTMLResponse)
def create_page(request: Request, db: Session = Depends(get_db)):
    user = require_login(request, db)
    from app.models import Zone, ZoneMembership
    my_zones = db.query(Zone).join(ZoneMembership).filter(
        ZoneMembership.user_id == user.id,
    ).all()
    return templates.TemplateResponse("create_post.html", {
        "request": request, "user": user, "categories": CATEGORIES,
        "zones": my_zones,
    })


@router.post("/create")
async def create_post(
    request: Request,
    content: str        = Form(...),
    category: str       = Form("general"),
    zone_id: str        = Form(""),
    poll_question: str  = Form(""),
    poll_options: str   = Form(""),  # comma-separated
    media: UploadFile   = File(None),
    db: Session         = Depends(get_db),
):
    user = require_login(request, db)
    
    zone_id_int = int(zone_id) if zone_id and zone_id.isdigit() else None
    options_list = [o.strip() for o in poll_options.split(",") if o.strip()]

    from app.services.post_service import PostService
    post = PostService.create_post(
        db=db, user_id=user.id, content=content, category=category,
        zone_id=zone_id_int, poll_question=poll_question.strip(), 
        poll_options=options_list, media=media
    )

    if post.zone_id:
        from app.models import Zone
        zone = db.query(Zone).filter(Zone.id == post.zone_id).first()
        if zone:
            return RedirectResponse(f"/zones/{zone.slug}", status_code=302)

    return RedirectResponse("/", status_code=302)


@router.get("/{post_id}", response_class=HTMLResponse)
def view_post(post_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_login(request, db)
    post = db.query(Post).options(
        joinedload(Post.author),
        joinedload(Post.comments).joinedload(Comment.author),
        joinedload(Post.liked_by),
        joinedload(Post.reactions),
        joinedload(Post.poll),
        joinedload(Post.zone),
    ).filter(Post.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404)

    log_interaction(db, user.id, post.id, "view")
    liked = any(u.id == user.id for u in post.liked_by)
    bookmarked = any(b.user_id == user.id for b in post.bookmarks)
    user_reaction = next((r for r in post.reactions if r.user_id == user.id), None)

    # Poll vote check
    user_poll_vote = None
    if post.poll:
        for opt in post.poll.options:
            for vote in opt.votes:
                if vote.user_id == user.id:
                    user_poll_vote = opt.id
                    break

    # Aggregate reactions
    reaction_counts = {}
    for r in post.reactions:
        reaction_counts[r.type] = reaction_counts.get(r.type, 0) + 1

    # Build comment replies tree
    comment_map = {}
    for c in post.comments:
        c.replies = []
        comment_map[c.id] = c
    for c in post.comments:
        if c.parent_id and c.parent_id in comment_map:
            comment_map[c.parent_id].replies.append(c)

    return templates.TemplateResponse("post_detail.html", {
        "request": request, "user": user, "post": post,
        "liked": liked, "like_count": len(post.liked_by),
        "bookmarked": bookmarked,
        "user_reaction": user_reaction,
        "reaction_counts": reaction_counts,
        "reaction_emojis": REACTION_EMOJIS,
        "user_poll_vote": user_poll_vote,
    })


@router.post("/{post_id}/like")
def like_post(post_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_login(request, db)
    post = db.query(Post).filter(Post.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404)
    already = any(u.id == user.id for u in post.liked_by)
    if already:
        post.liked_by.remove(user)
    else:
        post.liked_by.append(user)
        log_interaction(db, user.id, post.id, "like")
        if post.user_id != user.id:
            db.add(Notification(
                user_id=post.user_id, actor_id=user.id,
                type="like", reference_id=post.id, reference_type="post",
                message=f"{user.display_name} liked your post",
            ))
    db.commit()
    return JSONResponse({"liked": not already, "count": len(post.liked_by)})


@router.post("/{post_id}/react/{reaction_type}")
def react_to_post(post_id: int, reaction_type: str, request: Request, db: Session = Depends(get_db)):
    user = require_login(request, db)
    if reaction_type not in REACTION_EMOJIS:
        raise HTTPException(status_code=400)

    post = db.query(Post).filter(Post.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404)

    existing = db.query(Reaction).filter(
        Reaction.user_id == user.id, Reaction.post_id == post_id,
    ).first()

    if existing:
        if existing.type == reaction_type:
            db.delete(existing)
            db.commit()
            counts = {}
            for r in db.query(Reaction).filter(Reaction.post_id == post_id).all():
                counts[r.type] = counts.get(r.type, 0) + 1
            return JSONResponse({"removed": True, "counts": counts})
        else:
            existing.type = reaction_type
    else:
        db.add(Reaction(user_id=user.id, post_id=post_id, type=reaction_type))
        if post.user_id != user.id:
            db.add(Notification(
                user_id=post.user_id, actor_id=user.id,
                type="reaction", reference_id=post.id, reference_type="post",
                message=f"{user.display_name} reacted {REACTION_EMOJIS[reaction_type]} to your post",
            ))

    db.commit()
    counts = {}
    for r in db.query(Reaction).filter(Reaction.post_id == post_id).all():
        counts[r.type] = counts.get(r.type, 0) + 1
    return JSONResponse({"removed": False, "type": reaction_type, "counts": counts})


@router.post("/{post_id}/bookmark")
def bookmark_post(post_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_login(request, db)
    existing = db.query(Bookmark).filter(
        Bookmark.user_id == user.id, Bookmark.post_id == post_id,
    ).first()
    if existing:
        db.delete(existing)
        db.commit()
        return JSONResponse({"bookmarked": False})
    else:
        db.add(Bookmark(user_id=user.id, post_id=post_id))
        db.commit()
        return JSONResponse({"bookmarked": True})


@router.post("/{post_id}/comment")
def add_comment(
    post_id: int, request: Request,
    content: str = Form(...),
    parent_id: int = Form(None),
    db: Session  = Depends(get_db),
):
    user = require_login(request, db)
    post = db.query(Post).filter(Post.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404)
    db.add(Comment(content=content, user_id=user.id, post_id=post_id, parent_id=parent_id))
    log_interaction(db, user.id, post_id, "comment")

    if post.user_id != user.id:
        db.add(Notification(
            user_id=post.user_id, actor_id=user.id,
            type="comment", reference_id=post.id, reference_type="post",
            message=f"{user.display_name} commented on your post",
        ))
    db.commit()
    return RedirectResponse(f"/posts/{post_id}", status_code=302)


@router.post("/{post_id}/poll/{option_id}/vote")
def vote_poll(post_id: int, option_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_login(request, db)
    option = db.query(PollOption).filter(PollOption.id == option_id).first()
    if not option or option.poll.post_id != post_id:
        raise HTTPException(status_code=404)

    # Check if already voted
    existing = db.query(PollVote).join(PollOption).join(Poll).filter(
        Poll.post_id == post_id, PollVote.user_id == user.id,
    ).first()
    if existing:
        return JSONResponse({"error": "Already voted"})

    db.add(PollVote(option_id=option_id, user_id=user.id))
    db.commit()

    # Return updated counts
    poll = option.poll
    results = {}
    total = 0
    for opt in poll.options:
        count = len(opt.votes)
        results[opt.id] = count
        total += count

    return JSONResponse({"voted": option_id, "results": results, "total": total})


@router.post("/{post_id}/delete")
def delete_post(post_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_login(request, db)
    
    from app.services.post_service import PostService
    success = PostService.delete_post(db, post_id, user.id)
    if not success:
        return JSONResponse({"error": "Failed to delete post"}, status_code=403)
        
    return JSONResponse({"success": True})


