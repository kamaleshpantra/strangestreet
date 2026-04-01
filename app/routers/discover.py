from fastapi import APIRouter, Depends, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, func as sqlfunc
from database import get_db
from app.models import User, Interest, Connection, Notification, user_interests
from app.auth import get_current_user, require_login

router = APIRouter(prefix="/discover", tags=["discover"])
templates = Jinja2Templates(directory="app/templates")


@router.get("", response_class=HTMLResponse)
def discover_page(
    request: Request,
    category: str = "",
    db: Session = Depends(get_db),
):
    user = require_login(request, db)

    # Get all interest categories for filter bar
    categories = db.query(Interest.category).distinct().order_by(Interest.category).all()
    categories = [c[0] for c in categories]

    # Get current user's interest IDs
    my_interest_ids = {i.id for i in user.interests}

    if not my_interest_ids:
        # No interests selected — prompt to add some
        return templates.TemplateResponse("discover.html", {
            "request": request, "user": user, "profiles": [],
            "categories": categories, "selected_category": category,
            "no_interests": True,
        })

    # ── Try ML-scored recommendations first ───────────────────────────
    from app.models import PeopleScore
    ml_scores = db.query(PeopleScore).filter(
        PeopleScore.user_id == user.id
    ).order_by(PeopleScore.score.desc()).limit(50).all()

    if ml_scores:
        target_ids = [s.target_id for s in ml_scores]
        score_map = {s.target_id: s for s in ml_scores}

        # Filter by category if provided
        if category:
            cat_interest_ids = {
                i.id for i in db.query(Interest).filter(Interest.category == category).all()
            }
            filtered_ids = []
            for tid in target_ids:
                t_user = db.query(User).filter(User.id == tid).first()
                if t_user and any(i.id in cat_interest_ids for i in t_user.interests):
                    filtered_ids.append(tid)
            target_ids = filtered_ids

        targets = db.query(User).filter(
            User.id.in_(target_ids),
            User.is_active == True,
        ).all()
        target_by_id = {u.id: u for u in targets}

        profiles = []
        for tid in target_ids:
            u = target_by_id.get(tid)
            if not u:
                continue
            shared_interests = [i for i in u.interests if i.id in my_interest_ids]
            ps = score_map.get(tid)
            profiles.append({
                "user": u,
                "shared_count": len(shared_interests),
                "shared_interests": shared_interests[:8],
                "total_interests": len(u.interests),
                "ml_score": round(ps.score, 2) if ps else 0,
            })

        return templates.TemplateResponse("discover.html", {
            "request": request, "user": user, "profiles": profiles,
            "categories": categories, "selected_category": category,
            "no_interests": False,
        })

    # ── Fallback: SQL interest counting (original logic) ──────────────
    # Find users who share at least one interest, excluding self and already-connected
    connected_ids = set()
    for c in user.sent_connections:
        if c.status in ("pending", "accepted"):
            connected_ids.add(c.requested_id)
    for c in user.received_connections:
        if c.status in ("pending", "accepted"):
            connected_ids.add(c.requester_id)
    connected_ids.add(user.id)

    # Build query: users sharing interests
    # Subquery: count shared interests per user
    shared_count = (
        db.query(
            user_interests.c.user_id,
            sqlfunc.count(user_interests.c.interest_id).label("shared")
        )
        .filter(user_interests.c.interest_id.in_(my_interest_ids))
        .filter(user_interests.c.user_id.notin_(connected_ids))
        .group_by(user_interests.c.user_id)
        .subquery()
    )

    # Filter by category if provided
    if category:
        cat_interest_ids = [i.id for i in db.query(Interest).filter(Interest.category == category).all()]
        if cat_interest_ids:
            my_cat_ids = my_interest_ids & set(cat_interest_ids)
            if my_cat_ids:
                shared_count = (
                    db.query(
                        user_interests.c.user_id,
                        sqlfunc.count(user_interests.c.interest_id).label("shared")
                    )
                    .filter(user_interests.c.interest_id.in_(my_cat_ids))
                    .filter(user_interests.c.user_id.notin_(connected_ids))
                    .group_by(user_interests.c.user_id)
                    .subquery()
                )

    candidates = (
        db.query(User, shared_count.c.shared)
        .join(shared_count, User.id == shared_count.c.user_id)
        .filter(User.is_active == True)
        .filter(User.alias_name.isnot(None))  # must have alias set up
        .order_by(shared_count.c.shared.desc())
        .limit(50)
        .all()
    )

    profiles = []
    for u, shared in candidates:
        shared_interests = [i for i in u.interests if i.id in my_interest_ids]
        profiles.append({
            "user": u,
            "shared_count": shared,
            "shared_interests": shared_interests[:8],  # show up to 8
            "total_interests": len(u.interests),
        })

    return templates.TemplateResponse("discover.html", {
        "request": request, "user": user, "profiles": profiles,
        "categories": categories, "selected_category": category,
        "no_interests": False,
    })


@router.get("/profile/{user_id}", response_class=HTMLResponse)
def alias_profile(user_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_login(request, db)

    if user_id == user.id:
        return RedirectResponse(f"/users/{user.username}/edit", status_code=302)

    target = db.query(User).filter(User.id == user_id, User.is_active == True).first()
    if not target or not target.alias_name:
        raise HTTPException(status_code=404, detail="Profile not found")

    # Check existing connection
    connection = db.query(Connection).filter(
        or_(
            and_(Connection.requester_id == user.id, Connection.requested_id == user_id),
            and_(Connection.requester_id == user_id, Connection.requested_id == user.id),
        )
    ).first()

    # Shared interests
    my_interest_ids = {i.id for i in user.interests}
    shared_interests = [i for i in target.interests if i.id in my_interest_ids]
    unique_interests = [i for i in target.interests if i.id not in my_interest_ids]

    return templates.TemplateResponse("alias_profile.html", {
        "request": request, "user": user, "target": target,
        "connection": connection,
        "shared_interests": shared_interests,
        "unique_interests": unique_interests,
    })
