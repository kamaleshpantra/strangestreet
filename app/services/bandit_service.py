import math
from typing import List, Tuple
from app.models import Post

# Tuning parameters to balance the recommendation equation
W_SEMANTIC = 0.6  # Weight of the personalized ML SVD baseline
W_BANDIT = 0.4    # Weight given to real-time engagement and exploration

# Composite reward values
REWARD_CLICK = 0.2
REWARD_LIKE = 1.0
REWARD_REACTION = 1.5
REWARD_COMMENT = 3.0

def calculate_post_ucb(post: Post, ml_score: float, total_impressions: int) -> float:
    """
    Calculates the real-time UCB performance score of a single post,
    blending it with the baseline personalized ML score to prevent dilution.
    """
    
    # 1. Handle perfectly cold-start posts
    # If a post has never been seen, we assign it a very high uncertainty bonus 
    # to guarantee it gets shown so the algorithm can "explore" it.
    if post.impression_count == 0:
        return (W_SEMANTIC * ml_score) + (W_BANDIT * 99.0)

    # 2. Exploitation (The "Win Rate" based on deep engagement)
    # Calculate composite reward
    likes = len(post.liked_by) if post.liked_by else 0
    comments = len(post.comments) if post.comments else 0
    reactions = len(post.reactions) if post.reactions else 0
    clicks = post.click_count or 0
    
    total_reward = (
        (clicks * REWARD_CLICK) +
        (likes * REWARD_LIKE) + 
        (reactions * REWARD_REACTION) + 
        (comments * REWARD_COMMENT)
    )
    
    win_rate = total_reward / post.impression_count

    # 3. Exploration (The UCB "Uncertainty" Bonus)
    # We use a natural log curve. Total impressions is huge, post impressions is small = high bonus.
    # As the post gets viewed more, this bonus mathematically shrinks to 0.
    uncertainty_bonus = 0.0
    if total_impressions > 0:
        uncertainty_bonus = math.sqrt((2 * math.log(total_impressions)) / post.impression_count)

    # Calculate pure Bandit score
    bandit_score = win_rate + uncertainty_bonus
    
    # 4. Final Blend
    # Combine the deeply personalized AI prediction with the active community engagement
    final_score = (W_SEMANTIC * ml_score) + (W_BANDIT * bandit_score)
    return final_score

def rank_feed_with_bandit(posts_with_scores: List[Tuple[Post, float]]) -> List[Post]:
    """
    Accepts a list of tuples: (Post, ml_score)
    Returns the Posts ranked dynamically.
    """
    if not posts_with_scores:
        return []

    # Calculate global tracking denominator
    total_impressions = sum((p.impression_count or 0) for p, _ in posts_with_scores)
    
    # Calculate UCB for each post and attach to a new list
    ranked_posts = []
    for post, ml_score in posts_with_scores:
        ucb_blended_score = calculate_post_ucb(post, ml_score, total_impressions)
        ranked_posts.append((post, ucb_blended_score))
        
    # Sort descending strictly by our new Blended Bandit Score
    ranked_posts.sort(key=lambda x: x[1], reverse=True)
    
    # Return just the posts to the template
    return [post for post, score in ranked_posts]
