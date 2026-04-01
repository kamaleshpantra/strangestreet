from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_, desc
import numpy as np
from database import get_db
from app.models import User, Post, PostFeature, PeopleScore
from app.auth import get_current_user
from app.services.ml_service import MLService

router = APIRouter(tags=["search"])
templates = Jinja2Templates(directory="app/templates")

@router.get("/search", response_class=HTMLResponse)
def unified_search(
    request: Request,
    q: str = "",
    t: str = "posts",  # posts or people
    db: Session = Depends(get_db)
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/auth/login", status_code=302)

    results = []
    
    if not q:
        return templates.TemplateResponse("search.html", {
            "request": request, "user": user, "results": [], "query": q, "search_type": t
        })

    if t == "people":
        # Search Users (Keyword only)
        results = db.query(User).filter(
            or_(
                User.username.ilike(f"%{q}%"),
                User.display_name.ilike(f"%{q}%"),
            )
        ).limit(40).all()
        # Format for template
        results = [{"user": u} for u in results]

    else:
        # Search Posts (Hybrid: Keyword + Semantic)
        # 1. Keyword search
        kw_posts = db.query(Post).options(
            joinedload(Post.author),
            joinedload(Post.liked_by),
            joinedload(Post.comments),
            joinedload(Post.reactions),
            joinedload(Post.zone),
        ).filter(
            Post.content.ilike(f"%{q}%"),
            Post.is_flagged == False
        ).limit(50).all()

        # 2. Semantic search
        try:
            q_vec = MLService.encode_query(q)
            # Load post features (vectors)
            features = db.query(PostFeature).all()
            
            p_scores = []
            for pf in features:
                if not pf.topic_vector:
                    continue
                
                # Check if this post ID is already found via keyword (to avoid duplicates)
                p_vec = np.array(pf.topic_vector)
                # Compute dot product (MiniLM vectors are usually normalized)
                score = float(np.dot(q_vec, p_vec))
                
                if score > 0.35: # Similarity threshold
                    p_scores.append((pf.post_id, score))
            
            # Sort by semantic score
            p_scores.sort(key=lambda x: -x[1])
            semantic_ids = [pid for pid, score in p_scores[:40]]
            
            # Load semantic result objects
            sem_posts = db.query(Post).options(
                joinedload(Post.author),
                joinedload(Post.liked_by),
                joinedload(Post.comments),
                joinedload(Post.reactions),
                joinedload(Post.zone),
            ).filter(
                Post.id.in_(semantic_ids),
                Post.is_flagged == False
            ).all()
            
            post_map = {p.id: p for p in sem_posts}
            
            # Combine Keyword (Rank 1) and Semantic (Rank 2)
            final_posts = []
            seen_ids = set()
            
            # Keyword matches first
            for p in kw_posts:
                if p.id not in seen_ids:
                    final_posts.append(p)
                    seen_ids.add(p.id)
            
            # Semantic matches second
            for pid in semantic_ids:
                if pid in post_map and pid not in seen_ids:
                    final_posts.append(post_map[pid])
                    seen_ids.add(pid)
                    
            results = final_posts[:50]
        except Exception as e:
            print(f"  [Search] Semantic failed: {e}")
            results = kw_posts

    return templates.TemplateResponse("search.html", {
        "request": request, "user": user, "results": results, "query": q, "search_type": t
    })
