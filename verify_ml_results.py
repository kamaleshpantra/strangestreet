import sys; sys.path.insert(0,'.')
from database import SessionLocal
from app.models import User, Post, FeedScore, PeopleScore, ZoneScore, UserFeature, PostFeature, ContentFlag
from sqlalchemy import desc
db = SessionLocal()

print('\n' + '='*60)
print(' STRANGE STREET ML INTELLIGENCE PIPELINE RESULTS')
print('='*60)

# 1. Top Influencers (PageRank)
print('\n[1] Top 3 Influencers (Graph Engine - PageRank)')
print('    These users are the most central in the follower graph.')
top_influencers = db.query(User.username, UserFeature.pagerank, UserFeature.graph_degree).join(UserFeature).order_by(desc(UserFeature.pagerank)).limit(3).all()
for u, pr, deg in top_influencers:
    print(f'  - @{u}: PageRank={pr:.5f}, Connections={deg}')

# 2. People Recommendations
sample_user = db.query(User).filter(User.is_simulated == True).first()
if sample_user:
    print(f'\n[2] Top Stranger Recommendations for @{sample_user.username}')
    print('    Blends friend-of-friend topology + interest embeddings')
    recs = db.query(PeopleScore).filter(PeopleScore.user_id == sample_user.id).order_by(desc(PeopleScore.score)).limit(3).all()
    for r in recs:
        target_name = db.query(User.username).filter(User.id == r.target_id).scalar()
        print(f'  - Match: @{target_name} | Score: {r.score:.4f}')

# 3. Feed Recommendations
if sample_user:
    print(f'\n[3] Smart Feed Highlights for @{sample_user.username}')
    print('    Collaborative Filtering + Temporal Decay + Content Similarity')
    feed = db.query(FeedScore).filter(FeedScore.user_id == sample_user.id).order_by(desc(FeedScore.score)).limit(3).all()
    for f in feed:
        post = db.query(Post).filter(Post.id == f.post_id).first()
        author = db.query(User).filter(User.id == post.user_id).first()
        print(f'  - Post by @{author.username} | Fit Score: {f.score:.4f}')
        preview = post.content[:70].replace('\n', ' ')
        print(f'    \"{preview}...\"')

# 4. Toxicity Flags
print('\n[4] Content Safety Layer (Toxicity Diagnostics)')
print('    Posts penalized or flagged by heuristic NLP models.')
toxic = db.query(PostFeature).order_by(desc(PostFeature.toxicity_score)).limit(2).all()
if toxic and toxic[0].toxicity_score > 0:
    for t in toxic:
        post = db.query(Post).filter(Post.id == t.post_id).first()
        if t.toxicity_score > 0:
            print(f'  - Toxicity Score: {t.toxicity_score:.3f}')
            preview = post.content[:70].replace('\n', ' ')
            print(f'    \"{preview}...\"')
else:
    print('  - No highly toxic content detected in sample set.')

# 5. User Behavioral Features
print('\n[5] Behavioral Embeddings (Top Engaged Users)')
top_engaged = db.query(User.username, UserFeature.engagement_rate, UserFeature.activity_level).join(UserFeature).order_by(desc(UserFeature.engagement_rate)).limit(3).all()
for u, eng, act in top_engaged:
    print(f'  - @{u}: Engagement Rate={eng:.2f}, Activity Level/Mo={act:.2f}')

print('\n' + '='*60 + '\n')
