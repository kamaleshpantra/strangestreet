"""
Strange Street — Zone Recommender
===================================
Recommends zones to users based on:
  - Interest overlap with zone's most active topics
  - Louvain community → zone mapping
  - Friend/following overlap with zone members
  - Zone activity level

Writes results to ZoneScore table.

Usage:
    python ml/zone_recommender.py
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import random
import numpy as np
from collections import Counter
from sqlalchemy.orm import Session
from database import SessionLocal
from app.models import (
    User, Zone, ZoneMembership, Post, UserFeature,
    ZoneScore, user_interests,
)


# ── Config ────────────────────────────────────────────────────────────────
TOP_K_ZONES     = 10
W_INTEREST      = 0.35
W_COMMUNITY     = 0.20
W_MEMBER_OVERLAP = 0.25
W_ACTIVITY      = 0.20


def run(db: Session = None, graph_features: dict = None):
    """Run zone recommendation pipeline."""
    own_db = db is None
    if own_db:
        db = SessionLocal()

    try:
        print("  [Zone] Loading data...")

        users = db.query(User).filter(User.is_active == True).all()
        zones = db.query(Zone).all()

        if not zones:
            print("  [Zone] No zones found. Skipping.")
            return

        # User interests
        interest_rows = db.execute(user_interests.select()).fetchall()
        user_interest_map = {}
        for row in interest_rows:
            user_interest_map.setdefault(row.user_id, set()).add(row.interest_id)

        # Zone memberships
        memberships = db.query(ZoneMembership).all()
        zone_members = {}  # zone_id → set of user_ids
        user_zones = {}    # user_id → set of zone_ids
        for m in memberships:
            zone_members.setdefault(m.zone_id, set()).add(m.user_id)
            user_zones.setdefault(m.user_id, set()).add(m.zone_id)

        # Zone post activity (posts in last 30 days)
        zone_posts = db.query(Post.zone_id).filter(
            Post.zone_id.isnot(None)
        ).all()
        zone_activity = Counter(zid for (zid,) in zone_posts)
        max_activity = max(zone_activity.values()) if zone_activity else 1

        # Zone top interests: aggregate interests of zone members
        zone_interest_profile = {}
        for zone in zones:
            members = zone_members.get(zone.id, set())
            interest_counts = Counter()
            for mid in members:
                for iid in user_interest_map.get(mid, set()):
                    interest_counts[iid] += 1
            zone_interest_profile[zone.id] = set(interest_counts.keys())

        # User features (for community info)
        gf = graph_features or {}

        # Following sets for member overlap
        from app.models import followers as followers_table
        follow_rows = db.execute(followers_table.select()).fetchall()
        user_following = {}
        for row in follow_rows:
            user_following.setdefault(row.follower_id, set()).add(row.followed_id)

        # Clear old scores
        db.query(ZoneScore).delete()
        db.commit()

        # 4. Semantic interest overlap (BERT vectors)
        # Average member topic vector (BERT embeddings)
        zone_semantic_profile = {}
        for zone in zones:
            members = zone_members.get(zone.id, set())
            vectors = []
            for mid in members:
                # user_features table stores our new 384-dim BERT vectors
                # No change in schema, just re-running the feature engine
                uf = db.query(UserFeature).filter(UserFeature.user_id == mid).first()
                if uf and uf.topic_vector:
                    vectors.append(np.array(uf.topic_vector))
            if vectors:
                zone_semantic_profile[zone.id] = np.mean(vectors, axis=0)

        # User features for semantic overlap
        user_features_map = {uf.user_id: uf for uf in db.query(UserFeature).all()}

        # ── Scoring Loop ──────────────────────────────────────────────────
        print(f"  [Zone] Scoring {len(users)} users × {len(zones)} zones...")
        batch = []

        for user in users:
            uid = user.id
            uf = user_features_map.get(uid)
            my_zones = user_zones.get(uid, set())
            my_interests = user_interest_map.get(uid, set())
            my_community = gf.get(uid, {}).get("community_id", -1)
            my_following = user_following.get(uid, set())

            for zone in zones:
                zid = zone.id
                if zid in my_zones:
                    continue  # already a member

                # 1. Interest overlap (binary)
                z_interests = zone_interest_profile.get(zid, set())
                interest_score = 0.0
                if my_interests and z_interests:
                    interest_score = len(my_interests & z_interests) / len(my_interests | z_interests)

                # 1.1 Semantic interest overlap (BERT) - The "Smart" part
                semantic_score = 0.0
                if uf and uf.topic_vector and zid in zone_semantic_profile:
                    u_vec = np.array(uf.topic_vector)
                    z_vec = zone_semantic_profile[zid]
                    norm = np.linalg.norm(u_vec) * np.linalg.norm(z_vec)
                    if norm > 0:
                        semantic_score = float(np.dot(u_vec, z_vec) / norm)

                # 2. Community overlap
                z_members = zone_members.get(zid, set())
                community_score = 0.0
                if my_community >= 0 and z_members:
                    same_community = sum(
                        1 for mid in z_members
                        if gf.get(mid, {}).get("community_id") == my_community
                    )
                    community_score = same_community / len(z_members)

                # 3. Member overlap (following)
                member_overlap_score = 0.0
                if my_following and z_members:
                    friends_in_zone = len(my_following & z_members)
                    member_overlap_score = max(0, min(friends_in_zone / 3.0, 1.0))

                # 4. Activity level
                activity_score = zone_activity.get(zid, 0) / max_activity

                # Weighted sum - Giving high weight to semantic similarity
                # (Interest profile overlap is now split between Binary and Semantic)
                total = (
                    0.20 * interest_score +
                    0.25 * semantic_score +
                    0.15 * community_score +
                    0.20 * member_overlap_score +
                    0.20 * activity_score
                )

                if total > 0.05:
                    batch.append(ZoneScore(
                        user_id=uid,
                        zone_id=zid,
                        score=round(total, 4),
                    ))

        if batch:
            db.bulk_save_objects(batch)
            db.commit()

        total = db.query(ZoneScore).count()
        print(f"  [Zone] ✓ {total} zone scores written")

    finally:
        if own_db:
            db.close()


if __name__ == "__main__":
    print("═══ Strange Street Zone Recommender ═══\n")
    run()
    print("\n✓ Zone recommender complete.")
