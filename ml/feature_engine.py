"""
Strange Street — Feature Engine
================================
Computes text (TF-IDF + NMF topics), interest, and behavioral features
for all users and posts. Writes results to UserFeature / PostFeature tables.

Usage:
    python ml/feature_engine.py          # standalone
    Called by ml/run_pipeline.py         # orchestrated
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import numpy as np
import pandas as pd
from sklearn.decomposition import TruncatedSVD
from sqlalchemy.orm import Session
from database import SessionLocal
from app.models import (
    User, Post, Interest, InteractionLog,
    UserFeature, PostFeature, user_interests,
)
from datetime import datetime, timezone
from sentence_transformers import SentenceTransformer
import torch


# ── Config ────────────────────────────────────────────────────────────────
EMBEDDING_MODEL = "all-MiniLM-L6-v2"
N_INTEREST_DIM = 50     # reduced interest embedding dimension


class FeatureEngine:
    """Computes and caches all text, interest, and behavioral features."""

    def __init__(self, db: Session):
        self.db = db
        self.model = None
        self.interest_svd = TruncatedSVD(n_components=N_INTEREST_DIM, random_state=42)

    def get_model(self):
        """Lazy load the transformer model."""
        if self.model is None:
            print(f"  [Text] Loading {EMBEDDING_MODEL}...")
            # Use CPU for small models to avoid CUDA overhead if not needed
            self.model = SentenceTransformer(EMBEDDING_MODEL, device="cpu")
        return self.model

    # ── Text Features ─────────────────────────────────────────────────────

    def compute_text_features(self):
        """Sentence-BERT semantic embeddings for all post content."""
        print("  [Text] Loading posts...")
        posts = self.db.query(Post).all()
        if not posts:
            print("  [Text] No posts found. Skipping.")
            return {}, {}, None

        # Build corpus
        post_ids = [p.id for p in posts]
        corpus = [p.content or "" for p in posts]

        model = self.get_model()
        print(f"  [Text] Encoding {len(corpus)} posts into semantic space...")
        # batch_size for memory efficiency
        embeddings = model.encode(corpus, batch_size=32, show_progress_bar=True)

        post_topics = {}
        post_tfidf_norms = {}
        for i, pid in enumerate(post_ids):
            # Using 'topic_vector' column to store the 384-dim semantic vector
            post_topics[pid] = embeddings[i].tolist()
            # L2 norm of the embedding (usually ~1.0 for BERT)
            post_tfidf_norms[pid] = float(np.linalg.norm(embeddings[i]))

        print(f"  [Text] ✓ Computed semantic embeddings for {len(post_topics)} posts")
        return post_topics, post_tfidf_norms, embeddings

    def compute_user_topics(self, post_topics: dict) -> dict:
        """Aggregate post embeddings per user → user interest profile."""
        posts = self.db.query(Post.user_id, Post.id).all()

        user_post_map = {}
        for user_id, post_id in posts:
            user_post_map.setdefault(user_id, []).append(post_id)

        user_topics = {}
        for user_id, pids in user_post_map.items():
            vectors = [post_topics[pid] for pid in pids if pid in post_topics]
            if vectors:
                # Centroid of post history in semantic space
                user_topics[user_id] = np.mean(vectors, axis=0).tolist()

        print(f"  [Text] ✓ Computed semantic profiles for {len(user_topics)} users")
        return user_topics

    # ── Interest Features ─────────────────────────────────────────────────

    def compute_interest_embeddings(self) -> dict:
        """Binary interest vectors → reduced dense embeddings via SVD."""
        print("  [Interest] Loading user-interest matrix...")
        rows = self.db.execute(
            user_interests.select()
        ).fetchall()

        if not rows:
            print("  [Interest] No interest data found. Skipping.")
            return {}

        all_interest_ids = sorted(
            {r.interest_id for r in rows}
        )
        interest_idx = {iid: i for i, iid in enumerate(all_interest_ids)}

        user_ids = sorted({r.user_id for r in rows})
        user_idx = {uid: i for i, uid in enumerate(user_ids)}

        # Build binary matrix
        from scipy.sparse import lil_matrix
        matrix = lil_matrix((len(user_ids), len(all_interest_ids)))
        for r in rows:
            matrix[user_idx[r.user_id], interest_idx[r.interest_id]] = 1.0
        matrix = matrix.tocsr()

        # Reduce dimensions
        n_components = min(N_INTEREST_DIM, matrix.shape[1] - 1, matrix.shape[0] - 1)
        if n_components < 2:
            print("  [Interest] Too few interests for embedding. Skipping.")
            return {}

        self.interest_svd = TruncatedSVD(n_components=n_components, random_state=42)
        embeddings = self.interest_svd.fit_transform(matrix)

        result = {}
        for uid, idx in user_idx.items():
            result[uid] = embeddings[idx].tolist()

        print(f"  [Interest] ✓ {len(result)} user embeddings "
              f"({n_components} dims, "
              f"{self.interest_svd.explained_variance_ratio_.sum():.1%} variance)")
        return result

    # ── Behavioral Features ───────────────────────────────────────────────

    def compute_behavioral_features(self) -> dict:
        """Engagement rate, activity level, posting frequency per user."""
        print("  [Behavior] Computing behavioral features...")
        now = datetime.now(timezone.utc)

        # Interaction counts per user
        logs = self.db.query(InteractionLog).all()
        user_actions = {}
        for log in logs:
            user_actions.setdefault(log.user_id, []).append(log)

        # Post counts per user
        posts = self.db.query(Post.user_id, Post.id, Post.created_at).all()
        user_posts = {}
        for uid, pid, created_at in posts:
            user_posts.setdefault(uid, []).append(created_at)

        features = {}
        all_users = self.db.query(User.id).all()

        for (uid,) in all_users:
            actions = user_actions.get(uid, [])
            post_dates = user_posts.get(uid, [])

            # Engagement rate: (likes + comments) / total interactions
            likes = sum(1 for a in actions if a.action == "like")
            comments = sum(1 for a in actions if a.action == "comment")
            total = max(len(actions), 1)
            engagement_rate = (likes + comments) / total

            # Activity level: actions in last 30 days / 30
            recent_actions = sum(
                1 for a in actions
                if a.created_at and (now - a.created_at.replace(tzinfo=timezone.utc)).days < 30
            )
            activity_level = recent_actions / 30.0

            features[uid] = {
                "engagement_rate": round(engagement_rate, 4),
                "activity_level": round(activity_level, 4),
                "post_count": len(post_dates),
                "action_count": len(actions),
            }

        print(f"  [Behavior] ✓ Features for {len(features)} users")
        return features

    # ── Write to DB ───────────────────────────────────────────────────────

    def write_user_features(
        self, user_topics, interest_embeddings, behavioral, graph_features=None
    ):
        """Write all user-level features to UserFeature table."""
        print("  [Store] Writing user features to database...")

        # Clear old features
        self.db.query(UserFeature).delete()
        self.db.commit()

        all_user_ids = {uid for (uid,) in self.db.query(User.id).all()}
        batch = []

        for uid in all_user_ids:
            gf = (graph_features or {}).get(uid, {})
            bf = behavioral.get(uid, {})

            feature = UserFeature(
                user_id=uid,
                pagerank=gf.get("pagerank", 0.0),
                community_id=gf.get("community_id"),
                graph_degree=gf.get("degree", 0),
                topic_vector=user_topics.get(uid),
                interest_embedding=interest_embeddings.get(uid),
                engagement_rate=bf.get("engagement_rate", 0.0),
                activity_level=bf.get("activity_level", 0.0),
            )
            batch.append(feature)

        self.db.bulk_save_objects(batch)
        self.db.commit()
        print(f"  [Store] ✓ {len(batch)} user features written")

    def write_post_features(self, post_topics, post_tfidf_norms, toxicity_scores=None):
        """Write all post-level features to PostFeature table."""
        print("  [Store] Writing post features to database...")

        self.db.query(PostFeature).delete()
        self.db.commit()

        batch = []
        for pid in post_topics:
            feature = PostFeature(
                post_id=pid,
                topic_vector=post_topics[pid],
                tfidf_norm=post_tfidf_norms.get(pid, 0.0),
                toxicity_score=(toxicity_scores or {}).get(pid, 0.0),
            )
            batch.append(feature)

        self.db.bulk_save_objects(batch)
        self.db.commit()
        print(f"  [Store] ✓ {len(batch)} post features written")


def run(db: Session = None, graph_features: dict = None):
    """Run the full feature engine pipeline."""
    own_db = db is None
    if own_db:
        db = SessionLocal()

    try:
        engine = FeatureEngine(db)

        # Text features
        post_topics, post_tfidf_norms, _ = engine.compute_text_features()
        user_topics = engine.compute_user_topics(post_topics) if post_topics else {}

        # Interest embeddings
        interest_embeddings = engine.compute_interest_embeddings()

        # Behavioral features
        behavioral = engine.compute_behavioral_features()

        # Write to DB
        engine.write_user_features(
            user_topics, interest_embeddings, behavioral, graph_features
        )
        if post_topics:
            engine.write_post_features(post_topics, post_tfidf_norms)
        else:
            # Still write empty features for posts so other modules don't fail
            all_posts = db.query(Post).all()
            empty_topics = {p.id: [0.0] for p in all_posts}
            empty_norms = {p.id: 0.0 for p in all_posts}
            engine.write_post_features(empty_topics, empty_norms)

        return {
            "post_topics": post_topics,
            "user_topics": user_topics,
            "interest_embeddings": interest_embeddings,
            "behavioral": behavioral,
        }
    finally:
        if own_db:
            db.close()


if __name__ == "__main__":
    print("═══ Strange Street Feature Engine ═══\n")
    run()
    print("\n✓ Feature engine complete.")
