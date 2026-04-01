"""
Strange Street — Safety Module
================================
Content safety layer:
  - Keyword-based toxicity scoring (v1)
  - Author exposure capping
  - Interest diversity enforcement

Usage:
    python ml/safety.py
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import re
from sqlalchemy.orm import Session
from database import SessionLocal
from app.models import Post, PostFeature, ContentFlag, FeedScore


# ── Toxicity Keywords (v1 — heuristic) ───────────────────────────────────
# These are deliberately mild patterns for a social platform.
# V2 will replace this with a trained Jigsaw classifier.
TOXIC_PATTERNS = [
    r'\b(kill|murder|attack)\b.*\b(you|them|her|him)\b',
    r'\b(hate|despise)\b.*\b(you|them|people|everyone)\b',
    r'\b(stupid|idiot|moron|dumb)\b',
    r'\b(racist|sexist|homophobic)\b',
    r'\bdie\b.*\b(in a|you should)\b',
]

SPAM_PATTERNS = [
    r'(buy now|click here|free money|make \$\d+)',
    r'(DM me for|check my bio|link in bio)',
    r'(.)\1{5,}',  # repeated characters (e.g., "aaaaaa")
    r'https?://\S+.*https?://\S+',  # multiple URLs
]

MAX_AUTHOR_IN_FEED = 3  # max posts per author in any user's feed


def score_toxicity(text: str) -> float:
    """Score text toxicity (0.0 = safe, 1.0 = highly toxic)."""
    if not text:
        return 0.0

    text_lower = text.lower()
    hits = 0

    for pattern in TOXIC_PATTERNS:
        if re.search(pattern, text_lower):
            hits += 1

    for pattern in SPAM_PATTERNS:
        if re.search(pattern, text_lower):
            hits += 0.5

    total_patterns = len(TOXIC_PATTERNS) + len(SPAM_PATTERNS)
    return min(hits / max(total_patterns * 0.3, 1), 1.0)


def flag_toxic_posts(db: Session, threshold: float = 0.3):
    """Score all posts and flag those above threshold."""
    print("  [Safety] Scoring post toxicity...")

    posts = db.query(Post).filter(Post.is_flagged == False).all()
    flagged_count = 0
    batch = []

    for post in posts:
        score = score_toxicity(post.content)

        # Update post feature toxicity score
        pf = db.query(PostFeature).filter(PostFeature.post_id == post.id).first()
        if pf:
            pf.toxicity_score = score

        if score >= threshold:
            post.is_flagged = True
            post.flag_reason = f"auto_toxicity_{score:.2f}"
            batch.append(ContentFlag(
                post_id=post.id,
                flag_type="toxicity",
                confidence=score,
            ))
            flagged_count += 1

    if batch:
        db.bulk_save_objects(batch)
    db.commit()

    print(f"  [Safety] ✓ Scanned {len(posts)} posts, flagged {flagged_count}")
    return flagged_count


def enforce_author_diversity(db: Session, max_per_author: int = MAX_AUTHOR_IN_FEED):
    """
    In FeedScore table, ensure no single author has more than
    max_per_author posts in any user's feed.
    """
    print(f"  [Safety] Enforcing author cap ({max_per_author} per author)...")

    # Get all feed scores grouped by user
    scores = db.query(FeedScore).order_by(
        FeedScore.user_id, FeedScore.score.desc()
    ).all()

    user_scores = {}
    for s in scores:
        user_scores.setdefault(s.user_id, []).append(s)

    removed = 0
    for uid, user_feed in user_scores.items():
        # Get post → author mapping
        post_ids = [s.post_id for s in user_feed]
        posts = db.query(Post.id, Post.user_id).filter(Post.id.in_(post_ids)).all()
        post_author = {pid: author_id for pid, author_id in posts}

        author_count = {}
        for s in user_feed:
            author_id = post_author.get(s.post_id)
            if author_id:
                author_count[author_id] = author_count.get(author_id, 0) + 1
                if author_count[author_id] > max_per_author:
                    db.delete(s)
                    removed += 1

    db.commit()
    print(f"  [Safety] ✓ Removed {removed} excess author entries from feeds")
    return removed


def run(db: Session = None):
    """Run all safety checks."""
    own_db = db is None
    if own_db:
        db = SessionLocal()

    try:
        flagged = flag_toxic_posts(db)
        removed = enforce_author_diversity(db)
        return {"flagged": flagged, "author_capped": removed}
    finally:
        if own_db:
            db.close()


if __name__ == "__main__":
    print("═══ Strange Street Safety Module ═══\n")
    results = run()
    print(f"\n✓ Safety complete. {results}")
