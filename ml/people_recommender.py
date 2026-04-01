"""
Strange Street — People Recommender
=====================================
Recommends strangers to connect with using:
  - Friend-of-friend graph traversal
  - PageRank-weighted ranking
  - Louvain community overlap
  - Interest Jaccard similarity
  - Content similarity (TF-IDF topics)

Writes results to PeopleScore table.

Usage:
    python ml/people_recommender.py
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import numpy as np
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from database import SessionLocal
from app.models import (
    User, Connection, PeopleScore, UserFeature,
    user_interests,
)


# ── Config ────────────────────────────────────────────────────────────────
TOP_K_PEOPLE    = 20    # recommendations per user
MIN_SCORE       = 0.05  # skip very low scores

# Weights for blending signals
W_FOF           = 0.25  # friend-of-friend
W_PAGERANK      = 0.10  # target's influence
W_COMMUNITY     = 0.15  # same Louvain community
W_INTEREST      = 0.30  # Jaccard interest overlap
W_TOPIC         = 0.20  # content topic similarity


def jaccard_similarity(set_a: set, set_b: set) -> float:
    """Jaccard index between two sets."""
    if not set_a or not set_b:
        return 0.0
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    return intersection / union if union else 0.0


def cosine_similarity_vectors(a, b) -> float:
    """Cosine similarity between two lists/vectors."""
    if not a or not b:
        return 0.0
    a, b = np.array(a), np.array(b)
    norm = np.linalg.norm(a) * np.linalg.norm(b)
    return float(np.dot(a, b) / norm) if norm > 0 else 0.0


def run(db: Session = None, graph_features: dict = None):
    """Run people recommendation pipeline."""
    own_db = db is None
    if own_db:
        db = SessionLocal()

    try:
        print("  [People] Loading data...")

        # Load all active users
        users = db.query(User).filter(
            User.is_active == True,
        ).all()
        user_ids = {u.id for u in users}

        if len(users) < 5:
            print("  [People] Too few users for recommendations.")
            return

        # Load interest sets
        interest_rows = db.execute(user_interests.select()).fetchall()
        user_interest_map = {}
        for row in interest_rows:
            user_interest_map.setdefault(row.user_id, set()).add(row.interest_id)

        # Load existing connections/blocks
        connections = db.query(Connection).filter(
            Connection.status.in_(["pending", "accepted", "blocked"])
        ).all()
        connected_pairs = set()
        for c in connections:
            connected_pairs.add((c.requester_id, c.requested_id))
            connected_pairs.add((c.requested_id, c.requester_id))

        # Load user features from DB
        user_features = {}
        for uf in db.query(UserFeature).all():
            user_features[uf.user_id] = uf

        # Graph features (passed from graph_engine or loaded from DB)
        gf = graph_features or {}

        # Clear old scores
        db.query(PeopleScore).delete()
        db.commit()

        print(f"  [People] Scoring {len(users)} users...")

        batch = []
        scored = 0

        for user in users:
            uid = user.id
            my_interests = user_interest_map.get(uid, set())
            my_feature = user_features.get(uid)
            my_gf = gf.get(uid, {})
            my_community = my_gf.get("community_id", -1)
            my_fof = set(my_gf.get("fof_set", []))
            my_topics = my_feature.topic_vector if my_feature and my_feature.topic_vector else None

            candidates = []

            for target in users:
                tid = target.id
                if tid == uid:
                    continue
                if (uid, tid) in connected_pairs:
                    continue

                # Score components
                t_interests = user_interest_map.get(tid, set())
                t_feature = user_features.get(tid)
                t_gf = gf.get(tid, {})

                # 1. Friend-of-friend signal
                fof_score = 1.0 if tid in my_fof else 0.0

                # 2. PageRank (target's influence)
                pr_score = t_gf.get("pagerank", 0.0)

                # 3. Community overlap
                t_community = t_gf.get("community_id", -2)
                community_score = 1.0 if (
                    my_community >= 0 and my_community == t_community
                ) else 0.0

                # 4. Interest Jaccard
                interest_score = jaccard_similarity(my_interests, t_interests)

                # 5. Topic similarity
                t_topics = t_feature.topic_vector if t_feature and t_feature.topic_vector else None
                topic_score = cosine_similarity_vectors(my_topics, t_topics)

                # Weighted blend
                total_score = (
                    W_FOF * fof_score +
                    W_PAGERANK * pr_score +
                    W_COMMUNITY * community_score +
                    W_INTEREST * interest_score +
                    W_TOPIC * topic_score
                )

                if total_score >= MIN_SCORE:
                    candidates.append((tid, total_score, {
                        "fof": round(fof_score, 3),
                        "pagerank": round(pr_score, 3),
                        "community": round(community_score, 3),
                        "interest": round(interest_score, 3),
                        "topic": round(topic_score, 3),
                    }))

            # Top-K
            candidates.sort(key=lambda x: -x[1])
            for tid, score, breakdown in candidates[:TOP_K_PEOPLE]:
                batch.append(PeopleScore(
                    user_id=uid,
                    target_id=tid,
                    score=round(score, 4),
                    breakdown=breakdown,
                ))

            scored += 1
            if scored % 100 == 0:
                db.bulk_save_objects(batch)
                db.commit()
                batch = []
                print(f"    Scored {scored}/{len(users)} users")

        if batch:
            db.bulk_save_objects(batch)
            db.commit()

        total = db.query(PeopleScore).count()
        print(f"  [People] ✓ {total} people scores written")

    finally:
        if own_db:
            db.close()


if __name__ == "__main__":
    print("═══ Strange Street People Recommender ═══\n")
    run()
    print("\n✓ People recommender complete.")
