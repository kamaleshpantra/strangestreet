from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_, desc
import numpy as np
import re
from database import get_db
from app.models import User, Post, PostFeature, PeopleScore
from app.auth import get_current_user
from app.services.ml_service import MLService

router = APIRouter(tags=["search"])
templates = Jinja2Templates(directory="app/templates")

# Words too common to be meaningful in search
STOP_WORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "to", "of", "in", "for",
    "on", "with", "at", "by", "from", "as", "into", "about", "like",
    "through", "after", "over", "between", "out", "against", "during",
    "without", "before", "under", "around", "among", "it", "its",
    "i", "me", "my", "we", "our", "you", "your", "he", "she", "they",
    "them", "his", "her", "this", "that", "these", "those", "and", "but",
    "or", "nor", "not", "so", "if", "then", "than", "too", "very",
    "just", "also", "no", "yes", "up", "down", "here", "there", "when",
    "where", "how", "what", "which", "who", "whom", "why",
}

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
        
        # Extract meaningful search words from the query
        words = re.findall(r'[a-zA-Z0-9]+', q.lower())
        search_words = [w for w in words if w not in STOP_WORDS and len(w) >= 2]
        
        # 1. Keyword search — match posts containing ANY of the meaningful words
        kw_filters = []
        for word in search_words:
            kw_filters.append(Post.content.ilike(f"%{word}%"))
        
        kw_posts = []
        if kw_filters:
            kw_posts = db.query(Post).options(
                joinedload(Post.author),
                joinedload(Post.liked_by),
                joinedload(Post.comments),
                joinedload(Post.reactions),
                joinedload(Post.zone),
            ).filter(
                or_(*kw_filters),
                Post.is_flagged == False
            ).limit(50).all()
        
        # Score keyword results by how many search words appear as WHOLE WORDS
        # This prevents "ai" from matching "training" (substring false positive)
        kw_scored = {}
        for p in kw_posts:
            content_lower = (p.content or "").lower()
            word_hits = 0
            for w in search_words:
                # \b = word boundary: matches "ai" in "ai model" but NOT in "training"
                if re.search(r'\b' + re.escape(w) + r'\b', content_lower):
                    word_hits += 1
            if word_hits > 0:
                kw_scored[p.id] = {
                    "post": p,
                    "kw_score": word_hits / max(len(search_words), 1),
                }

        # 2. Semantic search
        try:
            q_vec = MLService.encode_query(q)
            # Load post features (vectors)
            features = db.query(PostFeature).all()
            
            sem_scored = {}
            for pf in features:
                if not pf.topic_vector:
                    continue
                
                p_vec = np.array(pf.topic_vector)
                score = float(np.dot(q_vec, p_vec))
                
                # Higher threshold to reduce false positives
                if score > 0.45:
                    sem_scored[pf.post_id] = score
            
            # Combine scores: keyword matches get a significant boost
            all_candidate_ids = set(kw_scored.keys()) | set(sem_scored.keys())
            
            combined = []
            for pid in all_candidate_ids:
                kw_info = kw_scored.get(pid)
                sem_score = sem_scored.get(pid, 0.0)
                kw_score = kw_info["kw_score"] if kw_info else 0.0
                
                # Combined: keyword match is weighted 60%, semantic 40%
                # Keyword matches are more trustworthy for intent
                final_score = (kw_score * 0.6) + (sem_score * 0.4)
                
                # Bonus for posts that match BOTH keyword and semantic
                if kw_score > 0 and sem_score > 0:
                    final_score += 0.15
                
                combined.append((pid, final_score))
            
            combined.sort(key=lambda x: -x[1])
            top_ids = [pid for pid, _ in combined[:50]]
            
            # Load any posts not already loaded via keyword
            missing_ids = [pid for pid in top_ids if pid not in kw_scored]
            extra_posts = {}
            if missing_ids:
                extras = db.query(Post).options(
                    joinedload(Post.author),
                    joinedload(Post.liked_by),
                    joinedload(Post.comments),
                    joinedload(Post.reactions),
                    joinedload(Post.zone),
                ).filter(
                    Post.id.in_(missing_ids),
                    Post.is_flagged == False
                ).all()
                extra_posts = {p.id: p for p in extras}
            
            # Build final ordered results
            final_posts = []
            for pid in top_ids:
                if pid in kw_scored:
                    final_posts.append(kw_scored[pid]["post"])
                elif pid in extra_posts:
                    final_posts.append(extra_posts[pid])
            
            results = final_posts
        except Exception as e:
            print(f"  [Search] Semantic failed: {e}")
            # Fallback to keyword-only, sorted by word match count
            sorted_kw = sorted(kw_scored.values(), key=lambda x: -x["kw_score"])
            results = [item["post"] for item in sorted_kw]

    return templates.TemplateResponse("search.html", {
        "request": request, "user": user, "results": results, "query": q, "search_type": t
    })


@router.get("/search/autocomplete")
def search_autocomplete(
    request: Request,
    q: str = "",
    db: Session = Depends(get_db)
):
    """Fast autocomplete suggestions for the search bar."""
    user = get_current_user(request, db)
    if not user or not q or len(q) < 2:
        return JSONResponse({"users": [], "posts": []})

    q_lower = q.lower().strip()

    # People suggestions — match username or display_name
    user_results = db.query(User).filter(
        User.is_active == True,
        or_(
            User.username.ilike(f"%{q_lower}%"),
            User.display_name.ilike(f"%{q_lower}%"),
        )
    ).limit(6).all()

    users_data = [{
        "username": u.username,
        "display_name": u.display_name,
        "avatar_url": u.avatar_url or "",
    } for u in user_results]

    # Post suggestions — match content words
    raw_posts = db.query(Post).options(
        joinedload(Post.author),
    ).filter(
        Post.content.ilike(f"%{q_lower}%"),
        Post.is_flagged == False,
    ).order_by(desc(Post.created_at)).limit(40).all()

    # Extract words to enforce word boundary
    words = re.findall(r'[a-zA-Z0-9]+', q_lower)
    search_words = [w for w in words if len(w) >= 2]

    post_results = []
    for p in raw_posts:
        content_lower = (p.content or "").lower()
        if search_words:
            # Enforce that the matched characters appear as whole words, not substrings
            if any(re.search(r'\b' + re.escape(w) + r'\b', content_lower) for w in search_words):
                post_results.append(p)
        else:
            post_results.append(p)
            
        if len(post_results) >= 4:
            break

    posts_data = [{
        "id": p.id,
        "snippet": (p.content or "")[:80],
        "author": p.author.display_name if p.author else "",
    } for p in post_results]

    return JSONResponse({"users": users_data, "posts": posts_data})
