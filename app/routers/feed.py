from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import desc
from database import get_db
from app.models import Post, User, Comment, FeedScore, Zone, ZoneMembership, Story, Reaction, ZoneScore
from app.auth import get_current_user
from datetime import datetime, timezone

router = APIRouter(tags=["feed"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/", response_class=HTMLResponse)
def home(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/auth/login", status_code=302)

    feed_posts = get_smart_feed(user, db)
    suggested  = get_suggested_users(user, db)

    # Story bar data
    now = datetime.now(timezone.utc)
    following_ids = [u.id for u in user.following] + [user.id]
    active_stories = db.query(Story).filter(
        Story.user_id.in_(following_ids),
        Story.expires_at > now,
    ).order_by(desc(Story.created_at)).all()

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

    ordered_stories = []
    if user.id in story_users:
        ordered_stories.append(story_users.pop(user.id))
    unviewed = [v for v in story_users.values() if not v["all_viewed"]]
    viewed = [v for v in story_users.values() if v["all_viewed"]]
    ordered_stories.extend(unviewed + viewed)

    # Zone Suggestions (SNA-based)
    zone_suggestions = db.query(Zone).join(
        ZoneScore, ZoneScore.zone_id == Zone.id
    ).filter(
        ZoneScore.user_id == user.id
    ).order_by(desc(ZoneScore.score)).limit(5).all()

    if not zone_suggestions:
        # Fallback to Trending zones if no ML scores are available
        zone_suggestions = db.query(Zone).order_by(desc(Zone.member_count)).limit(5).all()


    return templates.TemplateResponse("home.html", {
        "request":   request,
        "user":      user,
        "posts":     feed_posts,
        "suggested": suggested,
        "story_users": ordered_stories,
        "has_my_story": any(s.user_id == user.id for s in active_stories),
        "zone_suggestions": zone_suggestions,
    })


def get_smart_feed(user: User, db: Session):
    ml_scores = db.query(FeedScore).filter(
        FeedScore.user_id == user.id
    ).order_by(desc(FeedScore.score)).limit(50).all()

    if ml_scores:
        post_ids = [s.post_id for s in ml_scores]

        # Safety filter: exclude posts with high toxicity
        from app.models import PostFeature
        toxic_ids = set()
        toxic_features = db.query(PostFeature).filter(
            PostFeature.post_id.in_(post_ids),
            PostFeature.toxicity_score > 0.3,
        ).all()
        toxic_ids = {pf.post_id for pf in toxic_features}

        safe_ids = [pid for pid in post_ids if pid not in toxic_ids]

        posts_by_id = {
            p.id: p for p in db.query(Post).options(
                joinedload(Post.author),
                joinedload(Post.liked_by),
                joinedload(Post.comments),
                joinedload(Post.reactions),
                joinedload(Post.zone),
            ).filter(Post.id.in_(safe_ids), Post.is_flagged == False).all()
        }
        return [posts_by_id[pid] for pid in safe_ids if pid in posts_by_id]

    followed_ids = [u.id for u in user.following] + [user.id]

    # Also include posts from user's zones
    zone_ids = [m.zone_id for m in user.zone_memberships]

    from sqlalchemy import or_, literal

    filters = [Post.user_id.in_(followed_ids)]
    if zone_ids:
        filters.append(Post.zone_id.in_(zone_ids))

    posts = db.query(Post).options(
        joinedload(Post.author),
        joinedload(Post.liked_by),
        joinedload(Post.comments),
        joinedload(Post.reactions),
        joinedload(Post.zone),
    ).filter(
        Post.is_flagged == False,
        or_(*filters),
    ).order_by(desc(Post.created_at)).limit(40).all()

    return posts


def get_suggested_users(user: User, db: Session, limit: int = 5):
    following_ids = {u.id for u in user.following} | {user.id}
    all_users = db.query(User).filter(
        User.is_active == True,
        User.id.notin_(following_ids),
    ).all()
    ranked = sorted(all_users, key=lambda u: len(u.followers), reverse=True)
    return ranked[:limit]
