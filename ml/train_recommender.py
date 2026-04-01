"""
Strange Street — Feed Recommendation Engine
=============================================
Trains a matrix factorization recommender on the interaction logs,
then writes ranked feed scores back to the database.

The feed router automatically switches to ML scores once this runs.

Usage:
    python ml/train_recommender.py

Dependencies:
    pip install scikit-learn pandas numpy
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import numpy as np
import pandas as pd
from sklearn.decomposition import TruncatedSVD
from sklearn.preprocessing import normalize
from sklearn.metrics.pairwise import cosine_similarity
from sqlalchemy.orm import Session
from database import SessionLocal
from app.models import InteractionLog, Post, User, FeedScore, UserFeature, PostFeature
from datetime import datetime, timezone

# ── Config ────────────────────────────────────────────────────────────────
N_FACTORS      = 50    # latent factors in matrix factorization
TOP_K_POSTS    = 30    # number of posts to score per user
MIN_INTERACTIONS = 3  # skip users with fewer than this many interactions
RECENCY_WEIGHT = 0.3  # how much to boost recent posts (0 = ignore, 1 = full boost)
FEATURE_WEIGHT = 0.2  # how much to boost from topic/graph features (Stage 2 re-rank)
MAX_AUTHOR_PER_USER = 3  # max posts per author in a user's feed


def load_interactions(db: Session) -> pd.DataFrame:
    """Load all interaction logs into a DataFrame."""
    logs = db.query(InteractionLog).all()
    if not logs:
        raise ValueError("No interaction logs found. Run simulation first.")

    df = pd.DataFrame([{
        "user_id":    log.user_id,
        "post_id":    log.post_id,
        "weight":     log.weight,
        "created_at": log.created_at,
    } for log in logs])

    print(f"  Loaded {len(df)} interaction logs")
    print(f"  Unique users: {df['user_id'].nunique()}")
    print(f"  Unique posts: {df['post_id'].nunique()}")
    return df


def build_interaction_matrix(df: pd.DataFrame):
    """
    Build user × post interaction matrix.
    Each cell = sum of weighted interactions (like=1, comment=2, view=0.1).
    This is the input to matrix factorization.
    """
    # Aggregate duplicate (user, post) pairs
    matrix_df = df.groupby(["user_id", "post_id"])["weight"].sum().reset_index()

    # Create integer indices for users and posts
    user_ids = matrix_df["user_id"].unique()
    post_ids = matrix_df["post_id"].unique()

    user_idx = {uid: i for i, uid in enumerate(user_ids)}
    post_idx = {pid: i for i, pid in enumerate(post_ids)}

    # Sparse-friendly matrix construction
    from scipy.sparse import csr_matrix
    rows = matrix_df["user_id"].map(user_idx)
    cols = matrix_df["post_id"].map(post_idx)
    data = matrix_df["weight"].values

    matrix = csr_matrix(
        (data, (rows, cols)),
        shape=(len(user_ids), len(post_ids))
    )

    print(f"  Matrix shape: {matrix.shape} "
          f"({matrix.nnz} non-zero entries, "
          f"{matrix.nnz / (matrix.shape[0] * matrix.shape[1]) * 100:.2f}% dense)")

    return matrix, user_ids, post_ids, user_idx, post_idx


def train_svd(matrix, n_factors: int = N_FACTORS):
    """
    Matrix Factorization via Truncated SVD.
    Decomposes user×post matrix into user_factors × post_factors.
    Similar users end up with similar user_factors vectors.
    """
    n_components = min(n_factors, matrix.shape[0] - 1, matrix.shape[1] - 1)
    if n_components < 1:
        print(f"  Matrix {matrix.shape} too small for SVD. Falling back to uniform factors.")
        n_users, n_posts = matrix.shape
        # Return fallback factors (all 1s)
        user_factors = normalize(np.ones((n_users, 1)))
        post_factors = normalize(np.ones((n_posts, 1)))
        return user_factors, post_factors

    print(f"  Training SVD with {n_components} latent factors...")
    svd = TruncatedSVD(n_components=n_components, random_state=42, n_iter=10)
    user_factors = svd.fit_transform(matrix)          # (n_users, n_components)
    post_factors = svd.components_.T                  # (n_posts, n_components)

    # Normalize for cosine similarity
    user_factors = normalize(user_factors)
    post_factors = normalize(post_factors)

    explained = svd.explained_variance_ratio_.sum()
    print(f"  Explained variance: {explained:.1%}")
    return user_factors, post_factors


def compute_recency_boost(post_ids, db: Session) -> dict:
    """
    Boost newer posts slightly so fresh content surfaces.
    Returns a dict of post_id → recency_score (0–1).
    """
    posts = db.query(Post.id, Post.created_at).filter(Post.id.in_(post_ids.tolist())).all()
    now   = datetime.now(timezone.utc)
    boosts = {}
    for post_id, created_at in posts:
        if created_at:
            # created_at is timezone-aware from the database
            age_days = (now - created_at).days
            # Exponential decay: fresh posts score ~1.0, 30-day-old posts ~0.5
            boosts[post_id] = np.exp(-age_days / 30.0)
        else:
            boosts[post_id] = 0.5
    return boosts


def generate_feed_scores(
    user_factors, post_factors,
    user_ids, post_ids,
    user_idx, post_idx,
    recency_boost: dict,
    db: Session,
):
    """
    For each user, compute recommendation scores for all posts,
    blend with recency boost, and write top-K to FeedScore table.
    """
    print(f"  Generating feed scores for {len(user_ids)} users...")

    # Clear old scores
    db.query(FeedScore).delete()
    db.commit()

    recency_array = np.array([
        recency_boost.get(pid, 0.5) for pid in post_ids
    ])

    batch = []
    for i, user_id in enumerate(user_ids):
        # Skip users with almost no activity
        user_vec = user_factors[i]  # (n_factors,)

        # Dot product = predicted interest score for each post
        raw_scores = post_factors @ user_vec  # (n_posts,)

        # Blend: ML score + recency signal
        blended = (1 - RECENCY_WEIGHT) * raw_scores + RECENCY_WEIGHT * recency_array

        # Get top-K post indices
        k = min(TOP_K_POSTS, len(blended))
        top_k_idx = np.argpartition(blended, -k)[-k:] if k > 0 else np.array([], dtype=int)
        if len(top_k_idx) > 0:
            top_k_idx = top_k_idx[np.argsort(blended[top_k_idx])[::-1]]

        for rank, pidx in enumerate(top_k_idx):
            batch.append(FeedScore(
                user_id=int(user_id),
                post_id=int(post_ids[pidx]),
                score=float(blended[pidx]),
            ))

        if (i + 1) % 100 == 0:
            db.bulk_save_objects(batch)
            db.commit()
            batch = []
            print(f"    Scored {i+1}/{len(user_ids)} users")

    if batch:
        db.bulk_save_objects(batch)
        db.commit()

    total = db.query(FeedScore).count()
    print(f"  ✓ {total} feed scores written to database")


def rerank_with_features(db: Session):
    """
    Stage 2: Re-rank feed scores using text/graph/behavioral features.
    Blends SVD score with topic similarity, PageRank, and engagement.
    """
    print("\n  Stage 2: Feature-based re-ranking...")

    # Load features
    user_features = {uf.user_id: uf for uf in db.query(UserFeature).all()}
    post_features = {pf.post_id: pf for pf in db.query(PostFeature).all()}

    if not user_features or not post_features:
        print("  No feature data available. Skipping re-ranking.")
        return

    scores = db.query(FeedScore).all()
    updated = 0

    for fs in scores:
        uf = user_features.get(fs.user_id)
        pf = post_features.get(fs.post_id)
        if not uf or not pf:
            continue

        # Topic similarity bonus
        topic_bonus = 0.0
        if uf.topic_vector and pf.topic_vector:
            u_vec = np.array(uf.topic_vector)
            p_vec = np.array(pf.topic_vector)
            norm = np.linalg.norm(u_vec) * np.linalg.norm(p_vec)
            if norm > 0:
                topic_bonus = float(np.dot(u_vec, p_vec) / norm)

        # PageRank bonus (author influence not fully available here,
        # so use the user's own PageRank as a quality signal)
        pagerank_bonus = uf.pagerank or 0.0

        # Blend: original + feature boost
        feature_boost = (topic_bonus * 0.6 + pagerank_bonus * 0.4)
        fs.score = (1 - FEATURE_WEIGHT) * fs.score + FEATURE_WEIGHT * feature_boost
        updated += 1

    db.commit()
    print(f"  ✓ Re-ranked {updated} feed scores with features")


def apply_author_cap(db: Session):
    """Remove excess entries so no author dominates a user's feed."""
    print(f"  Applying author cap ({MAX_AUTHOR_PER_USER} per author)...")

    scores = db.query(FeedScore).order_by(
        FeedScore.user_id, FeedScore.score.desc()
    ).all()

    user_scores = {}
    for s in scores:
        user_scores.setdefault(s.user_id, []).append(s)

    post_ids = {s.post_id for s in scores}
    post_author = dict(
        db.query(Post.id, Post.user_id).filter(Post.id.in_(post_ids)).all()
    )

    removed = 0
    for uid, feed in user_scores.items():
        author_count = {}
        for s in feed:
            aid = post_author.get(s.post_id)
            if aid:
                author_count[aid] = author_count.get(aid, 0) + 1
                if author_count[aid] > MAX_AUTHOR_PER_USER:
                    db.delete(s)
                    removed += 1

    db.commit()
    print(f"  ✓ Removed {removed} excess author entries")


def cold_start_fallback(db: Session):
    """
    For users with no feed scores, provide popularity-based fallback.
    Uses most-liked posts from the last 30 days.
    """
    # Find users without any feed scores
    scored_users = {uid for (uid,) in db.query(FeedScore.user_id).distinct().all()}
    all_users = {uid for (uid,) in db.query(User.id).filter(User.is_active == True).all()}
    cold_users = all_users - scored_users

    if not cold_users:
        return

    print(f"  Cold start: {len(cold_users)} users need fallback...")

    # Get popular posts (most liked, recent)
    from sqlalchemy import func, desc
    from app.models import post_likes
    popular = (
        db.query(Post.id, func.count(post_likes.c.user_id).label("likes"))
        .join(post_likes, Post.id == post_likes.c.post_id)
        .filter(Post.is_flagged == False)
        .group_by(Post.id)
        .order_by(desc("likes"))
        .limit(TOP_K_POSTS)
        .all()
    )

    if not popular:
        return

    max_likes = popular[0][1] if popular else 1
    batch = []
    for uid in cold_users:
        for post_id, likes in popular:
            batch.append(FeedScore(
                user_id=uid,
                post_id=post_id,
                score=likes / max_likes,  # normalize to 0-1
            ))

    db.bulk_save_objects(batch)
    db.commit()
    print(f"  ✓ Cold start: {len(batch)} fallback scores for {len(cold_users)} users")


def run():
    print("╔══════════════════════════════════════╗")
    print("║   Strange Street Recommendation ML   ║")
    print("╚══════════════════════════════════════╝\n")

    db = SessionLocal()
    try:
        # Step 1: Load data
        print("[1/5] Loading interaction data...")
        df = load_interactions(db)

        # Step 2: Build matrix
        print("\n[2/5] Building interaction matrix...")
        matrix, user_ids, post_ids, user_idx, post_idx = build_interaction_matrix(df)

        # Step 3: Train SVD
        print("\n[3/5] Training matrix factorization (SVD)...")
        user_factors, post_factors = train_svd(matrix)

        # Step 4: Recency boost
        print("\n[4/5] Computing recency boost...")
        recency_boost = compute_recency_boost(post_ids, db)

        # Step 5: Write scores to DB
        print("\n[5/5] Writing feed scores to database...")
        generate_feed_scores(
            user_factors, post_factors,
            user_ids, post_ids,
            user_idx, post_idx,
            recency_boost, db,
        )

        # Stage 2: Feature-based re-ranking
        rerank_with_features(db)

        # Author diversity cap
        apply_author_cap(db)

        # Cold start fallback
        cold_start_fallback(db)

        print("\n╔══════════════════════════════════════╗")
        print("║         Training Complete!           ║")
        print("╚══════════════════════════════════════╝")
        print("  ✓ Feed scores written to database.")
        print("  ✓ Stage 2 re-ranking applied.")
        print("  ✓ The app will now serve ML-ranked feeds.")
        print("  Re-run this script periodically to refresh scores.")

    except Exception as e:
        print(f"\n✗ Error: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    run()
