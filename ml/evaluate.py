"""
Strange Street — Evaluation Module
====================================
Offline evaluation metrics for the ML pipeline:
  - Precision@K (feed relevance)
  - Coverage (catalog diversity)
  - Diversity score (interest category spread per feed)

Usage:
    python ml/evaluate.py
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from collections import Counter
from sqlalchemy.orm import Session
from database import SessionLocal
from app.models import (
    Post, User, FeedScore, InteractionLog,
    PeopleScore, ZoneScore, ContentFlag,
)


def precision_at_k(db: Session, k: int = 10) -> dict:
    """
    Precision@K: Of the top-K recommended posts per user,
    how many did the user actually engage with (like/comment)?
    Uses historical interactions as ground truth.
    """
    print(f"  [Eval] Computing Precision@{k}...")

    # Build ground truth: user_id → set of post_ids they engaged with
    interactions = db.query(InteractionLog).filter(
        InteractionLog.action.in_(["like", "comment"])
    ).all()

    ground_truth = {}
    for log in interactions:
        ground_truth.setdefault(log.user_id, set()).add(log.post_id)

    # Get top-K recommended posts per user
    scores = db.query(FeedScore).order_by(
        FeedScore.user_id, FeedScore.score.desc()
    ).all()

    user_recs = {}
    for s in scores:
        user_recs.setdefault(s.user_id, []).append(s.post_id)

    # Compute precision per user
    precisions = []
    for uid, recs in user_recs.items():
        top_k = recs[:k]
        truth = ground_truth.get(uid, set())
        if truth:
            hits = sum(1 for pid in top_k if pid in truth)
            precisions.append(hits / k)

    avg_precision = sum(precisions) / len(precisions) if precisions else 0.0
    return {
        "precision_at_k": round(avg_precision, 4),
        "k": k,
        "users_evaluated": len(precisions),
    }


def catalog_coverage(db: Session) -> dict:
    """
    Coverage: What fraction of all posts appear in at least
    one user's recommended feed?
    """
    print("  [Eval] Computing catalog coverage...")

    total_posts = db.query(Post).filter(Post.is_flagged == False).count()
    recommended_posts = db.query(FeedScore.post_id).distinct().count()

    coverage = recommended_posts / max(total_posts, 1)
    return {
        "coverage": round(coverage, 4),
        "recommended_posts": recommended_posts,
        "total_posts": total_posts,
    }


def feed_diversity(db: Session) -> dict:
    """
    Diversity: Average number of distinct post categories
    per user's feed recommendations.
    """
    print("  [Eval] Computing feed diversity...")

    scores = db.query(FeedScore).all()
    user_posts = {}
    for s in scores:
        user_posts.setdefault(s.user_id, []).append(s.post_id)

    # Get post categories
    all_post_ids = set()
    for pids in user_posts.values():
        all_post_ids.update(pids)

    posts = db.query(Post.id, Post.category).filter(Post.id.in_(all_post_ids)).all()
    post_category = {pid: cat for pid, cat in posts}

    diversity_scores = []
    for uid, pids in user_posts.items():
        categories = set()
        for pid in pids:
            cat = post_category.get(pid)
            if cat:
                categories.add(cat)
        diversity_scores.append(len(categories))

    avg_diversity = sum(diversity_scores) / max(len(diversity_scores), 1)
    return {
        "avg_categories_per_feed": round(avg_diversity, 2),
        "users_evaluated": len(diversity_scores),
    }


def pipeline_summary(db: Session) -> dict:
    """Quick summary of pipeline outputs."""
    return {
        "feed_scores": db.query(FeedScore).count(),
        "people_scores": db.query(PeopleScore).count(),
        "zone_scores": db.query(ZoneScore).count(),
        "content_flags": db.query(ContentFlag).count(),
    }


def run(db: Session = None):
    """Run all evaluation metrics and print report."""
    own_db = db is None
    if own_db:
        db = SessionLocal()

    try:
        p_at_k = precision_at_k(db)
        coverage = catalog_coverage(db)
        diversity = feed_diversity(db)
        summary = pipeline_summary(db)

        print("\n╔══════════════════════════════════════╗")
        print("║     ML Pipeline Evaluation Report    ║")
        print("╚══════════════════════════════════════╝")
        print(f"\n  Feed Scores:     {summary['feed_scores']}")
        print(f"  People Scores:   {summary['people_scores']}")
        print(f"  Zone Scores:     {summary['zone_scores']}")
        print(f"  Content Flags:   {summary['content_flags']}")
        print(f"\n  Precision@{p_at_k['k']}:    {p_at_k['precision_at_k']:.4f} "
              f"({p_at_k['users_evaluated']} users)")
        print(f"  Coverage:        {coverage['coverage']:.1%} "
              f"({coverage['recommended_posts']}/{coverage['total_posts']} posts)")
        print(f"  Avg Diversity:   {diversity['avg_categories_per_feed']:.1f} categories/feed "
              f"({diversity['users_evaluated']} users)")

        return {
            "precision": p_at_k,
            "coverage": coverage,
            "diversity": diversity,
            "summary": summary,
        }

    finally:
        if own_db:
            db.close()


if __name__ == "__main__":
    run()
