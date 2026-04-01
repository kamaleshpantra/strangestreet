from sqlalchemy import (
    Column, Integer, String, Text, Boolean,
    DateTime, ForeignKey, Float, Enum, JSON
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base
import enum


# ── Association Tables ───────────────────────────────────────────────────────
from sqlalchemy import Table

followers = Table(
    "followers",
    Base.metadata,
    Column("follower_id", Integer, ForeignKey("users.id"), primary_key=True, index=True),
    Column("followed_id", Integer, ForeignKey("users.id"), primary_key=True, index=True),
)

post_likes = Table(
    "post_likes",
    Base.metadata,
    Column("user_id",  Integer, ForeignKey("users.id"),  primary_key=True, index=True),
    Column("post_id",  Integer, ForeignKey("posts.id"),  primary_key=True, index=True),
)

user_interests = Table(
    "user_interests",
    Base.metadata,
    Column("user_id",    Integer, ForeignKey("users.id"),     primary_key=True),
    Column("interest_id", Integer, ForeignKey("interests.id"), primary_key=True),
)


# ── Interest ─────────────────────────────────────────────────────────────────
class Interest(Base):
    __tablename__ = "interests"

    id       = Column(Integer, primary_key=True, index=True)
    name     = Column(String(100), unique=True, nullable=False, index=True)
    category = Column(String(50),  nullable=False, index=True)
    icon     = Column(String(10),  nullable=True)   # emoji

    users = relationship("User", secondary=user_interests, back_populates="interests")


# ── User ─────────────────────────────────────────────────────────────────────
class User(Base):
    __tablename__ = "users"

    id              = Column(Integer, primary_key=True, index=True)
    username        = Column(String(50),  unique=True, nullable=False, index=True)
    email           = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    display_name    = Column(String(100), nullable=True)
    bio             = Column(Text, nullable=True)
    avatar_url      = Column(String(500), nullable=True)
    is_active       = Column(Boolean, default=True)
    is_simulated    = Column(Boolean, default=False)
    is_verified     = Column(Boolean, default=False)
    relationship_status  = Column(String(30), nullable=True)

    # Alias profile (separate from public)
    alias_name              = Column(String(50),  nullable=True)
    alias_bio               = Column(Text, nullable=True)
    alias_relationship_status = Column(String(30), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    public_key = Column(Text, nullable=True)

    # Relationships
    posts    = relationship("Post",    back_populates="author",  cascade="all, delete")
    comments = relationship("Comment", back_populates="author",  cascade="all, delete")

    following = relationship(
        "User",
        secondary=followers,
        primaryjoin=id == followers.c.follower_id,
        secondaryjoin=id == followers.c.followed_id,
        backref="followers",
    )

    liked_posts = relationship("Post", secondary=post_likes, back_populates="liked_by")
    interests   = relationship("Interest", secondary=user_interests, back_populates="users")

    # Connections
    sent_connections     = relationship("Connection", foreign_keys="Connection.requester_id", back_populates="requester")
    received_connections = relationship("Connection", foreign_keys="Connection.requested_id", back_populates="requested")

    # Messages
    sent_messages     = relationship("Message", foreign_keys="Message.sender_id",   back_populates="sender")
    received_messages = relationship("Message", foreign_keys="Message.receiver_id", back_populates="receiver")

    # Stories
    stories = relationship("Story", back_populates="author", cascade="all, delete")

    # Notifications
    notifications = relationship("Notification", foreign_keys="Notification.user_id", back_populates="user", cascade="all, delete")

    # Bookmarks
    bookmarks = relationship("Bookmark", back_populates="user", cascade="all, delete")

    # Reactions
    reactions = relationship("Reaction", back_populates="user", cascade="all, delete")

    # Zone memberships
    zone_memberships = relationship("ZoneMembership", back_populates="user", cascade="all, delete")


# ── Post ──────────────────────────────────────────────────────────────────────
class Post(Base):
    __tablename__ = "posts"

    id          = Column(Integer, primary_key=True, index=True)
    content     = Column(Text, nullable=False)
    image_url   = Column(Text, nullable=True)
    media_type  = Column(String(10), nullable=True)   # "image" or "video"
    category    = Column(String(50),  nullable=True)
    user_id     = Column(Integer, ForeignKey("users.id"), nullable=False)
    zone_id     = Column(Integer, ForeignKey("zones.id"), nullable=True)  # if posted in a zone
    is_flagged  = Column(Boolean, default=False)
    flag_reason = Column(String(100), nullable=True)
    is_pinned   = Column(Boolean, default=False)
    flair_id    = Column(Integer, ForeignKey("zone_flairs.id", ondelete="SET NULL"), nullable=True)
    created_at  = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    author    = relationship("User",    back_populates="posts")
    comments  = relationship("Comment", back_populates="post", cascade="all, delete")
    liked_by  = relationship("User",    secondary=post_likes,  back_populates="liked_posts")
    reactions = relationship("Reaction", back_populates="post", cascade="all, delete")
    bookmarks = relationship("Bookmark", back_populates="post", cascade="all, delete")
    zone      = relationship("Zone",    back_populates="posts")
    poll      = relationship("Poll",    back_populates="post",  uselist=False, cascade="all, delete")
    flair     = relationship("ZoneFlair")


# ── Comment ───────────────────────────────────────────────────────────────────
class Comment(Base):
    __tablename__ = "comments"

    id         = Column(Integer, primary_key=True, index=True)
    content    = Column(Text,    nullable=False)
    user_id    = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    post_id    = Column(Integer, ForeignKey("posts.id"), nullable=False, index=True)
    parent_id  = Column(Integer, ForeignKey("comments.id", ondelete="CASCADE"), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    author = relationship("User", back_populates="comments")
    post   = relationship("Post", back_populates="comments")
    
    replies = relationship("Comment", back_populates="parent", cascade="all, delete", foreign_keys=[parent_id])
    parent  = relationship("Comment", back_populates="replies", remote_side=[id], foreign_keys=[parent_id])


# ── Interaction log (for ML training) ────────────────────────────────────────
class InteractionLog(Base):
    __tablename__ = "interaction_logs"

    id         = Column(Integer, primary_key=True, index=True)
    user_id    = Column(Integer, ForeignKey("users.id"), nullable=False)
    post_id    = Column(Integer, ForeignKey("posts.id"), nullable=False)
    action     = Column(String(20), nullable=False)
    weight     = Column(Float, default=0.0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


# ── Feed score cache (ML output) ─────────────────────────────────────────────
class FeedScore(Base):
    __tablename__ = "feed_scores"

    id         = Column(Integer, primary_key=True, index=True)
    user_id    = Column(Integer, ForeignKey("users.id"), nullable=False)
    post_id    = Column(Integer, ForeignKey("posts.id"), nullable=False)
    score      = Column(Float,   default=0.0)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


# ── Connection (stranger connections) ────────────────────────────────────────
class Connection(Base):
    __tablename__ = "connections"

    id            = Column(Integer, primary_key=True, index=True)
    requester_id  = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    requested_id  = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    status        = Column(String(20), default="pending", nullable=False, index=True)  # pending, accepted, rejected, blocked
    created_at    = Column(DateTime(timezone=True), server_default=func.now())
    updated_at    = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    requester = relationship("User", foreign_keys=[requester_id], back_populates="sent_connections")
    requested = relationship("User", foreign_keys=[requested_id], back_populates="received_connections")
    messages  = relationship("Message", back_populates="connection", cascade="all, delete")
    reveals   = relationship("Reveal",  back_populates="connection", cascade="all, delete")


# ── Message ──────────────────────────────────────────────────────────────────
class Message(Base):
    __tablename__ = "messages"

    id            = Column(Integer, primary_key=True, index=True)
    sender_id     = Column(Integer, ForeignKey("users.id"), nullable=False)
    receiver_id   = Column(Integer, ForeignKey("users.id"), nullable=False)
    connection_id = Column(Integer, ForeignKey("connections.id"), nullable=True)  # null = public DM
    content       = Column(Text, nullable=False)
    media_url     = Column(String(500), nullable=True)
    media_type    = Column(String(20), nullable=True)  # 'image', 'video', 'file'
    file_name     = Column(String(200), nullable=True) # for downloads
    is_read       = Column(Boolean, default=False)
    created_at    = Column(DateTime(timezone=True), server_default=func.now())

    sender     = relationship("User", foreign_keys=[sender_id],   back_populates="sent_messages")
    receiver   = relationship("User", foreign_keys=[receiver_id], back_populates="received_messages")
    connection = relationship("Connection", back_populates="messages")


# ── Reveal (progressive info disclosure) ─────────────────────────────────────
class Reveal(Base):
    __tablename__ = "reveals"

    id            = Column(Integer, primary_key=True, index=True)
    connection_id = Column(Integer, ForeignKey("connections.id"), nullable=False)
    user_id       = Column(Integer, ForeignKey("users.id"), nullable=False)
    level         = Column(Integer, default=0)  # 0=alias, 1=public bio, 2=username, 3=profile pic
    created_at    = Column(DateTime(timezone=True), server_default=func.now())

    connection = relationship("Connection", back_populates="reveals")
    user       = relationship("User")


# ── Zone (community) ────────────────────────────────────────────────────────
class Zone(Base):
    __tablename__ = "zones"

    id           = Column(Integer, primary_key=True, index=True)
    name         = Column(String(100), unique=True, nullable=False, index=True)
    slug         = Column(String(120), unique=True, nullable=False, index=True)
    description  = Column(Text, nullable=True)
    icon_url     = Column(String(500), nullable=True)
    banner_url   = Column(String(500), nullable=True)
    zone_type    = Column(String(20), default="public")  # public, private, restricted
    rules        = Column(Text, nullable=True)
    creator_id   = Column(Integer, ForeignKey("users.id"), nullable=False)
    member_count = Column(Integer, default=0)
    created_at   = Column(DateTime(timezone=True), server_default=func.now())

    creator     = relationship("User")
    memberships = relationship("ZoneMembership", back_populates="zone", cascade="all, delete")
    posts       = relationship("Post", back_populates="zone")


# ── Zone Membership ──────────────────────────────────────────────────────────
class ZoneMembership(Base):
    __tablename__ = "zone_memberships"

    id        = Column(Integer, primary_key=True, index=True)
    user_id   = Column(Integer, ForeignKey("users.id"),  nullable=False)
    zone_id   = Column(Integer, ForeignKey("zones.id"),  nullable=False)
    role      = Column(String(20), default="member")  # member, moderator, admin
    joined_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User",  back_populates="zone_memberships")
    zone = relationship("Zone",  back_populates="memberships")


# ── Zone Flair ───────────────────────────────────────────────────────────────
class ZoneFlair(Base):
    __tablename__ = "zone_flairs"

    id        = Column(Integer, primary_key=True, index=True)
    zone_id   = Column(Integer, ForeignKey("zones.id", ondelete="CASCADE"), nullable=False)
    name      = Column(String(50), nullable=False)
    color_hex = Column(String(7), default="#4B5563")

    zone = relationship("Zone")

# ── Zone Ban ─────────────────────────────────────────────────────────────────
class ZoneBan(Base):
    __tablename__ = "zone_bans"

    id         = Column(Integer, primary_key=True, index=True)
    zone_id    = Column(Integer, ForeignKey("zones.id", ondelete="CASCADE"), nullable=False)
    user_id    = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    reason     = Column(String(200), nullable=True)
    banned_at  = Column(DateTime(timezone=True), server_default=func.now())

    zone = relationship("Zone")
    user = relationship("User")


# ── Story ────────────────────────────────────────────────────────────────────
class Story(Base):
    __tablename__ = "stories"

    id         = Column(Integer, primary_key=True, index=True)
    user_id    = Column(Integer, ForeignKey("users.id"), nullable=False)
    media_url  = Column(String(500), nullable=False)
    media_type = Column(String(10), default="image")  # image or video
    caption    = Column(String(200), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=False)

    author = relationship("User", back_populates="stories")
    views  = relationship("StoryView", back_populates="story", cascade="all, delete")


# ── Story View ───────────────────────────────────────────────────────────────
class StoryView(Base):
    __tablename__ = "story_views"

    id        = Column(Integer, primary_key=True, index=True)
    story_id  = Column(Integer, ForeignKey("stories.id"), nullable=False)
    viewer_id = Column(Integer, ForeignKey("users.id"),   nullable=False)
    viewed_at = Column(DateTime(timezone=True), server_default=func.now())

    story  = relationship("Story", back_populates="views")
    viewer = relationship("User")


# ── Notification ─────────────────────────────────────────────────────────────
class Notification(Base):
    __tablename__ = "notifications"

    id           = Column(Integer, primary_key=True, index=True)
    user_id      = Column(Integer, ForeignKey("users.id"), nullable=False)
    actor_id     = Column(Integer, ForeignKey("users.id"), nullable=True)
    type         = Column(String(30), nullable=False)  # like, comment, follow, connection, zone_invite, mention, message, reaction
    reference_id = Column(Integer, nullable=True)       # post_id, connection_id, etc.
    reference_type = Column(String(30), nullable=True)  # post, connection, zone, message
    message      = Column(String(300), nullable=True)
    is_read      = Column(Boolean, default=False)
    created_at   = Column(DateTime(timezone=True), server_default=func.now())

    user  = relationship("User", foreign_keys=[user_id],  back_populates="notifications")
    actor = relationship("User", foreign_keys=[actor_id])


# ── Bookmark ─────────────────────────────────────────────────────────────────
class Bookmark(Base):
    __tablename__ = "bookmarks"

    id         = Column(Integer, primary_key=True, index=True)
    user_id    = Column(Integer, ForeignKey("users.id"), nullable=False)
    post_id    = Column(Integer, ForeignKey("posts.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="bookmarks")
    post = relationship("Post", back_populates="bookmarks")


# ── Reaction ─────────────────────────────────────────────────────────────────
class Reaction(Base):
    __tablename__ = "reactions"

    id         = Column(Integer, primary_key=True, index=True)
    user_id    = Column(Integer, ForeignKey("users.id"), nullable=False)
    post_id    = Column(Integer, ForeignKey("posts.id"), nullable=False)
    type       = Column(String(20), nullable=False)  # fire, love, laugh, mind_blown, clap, dead
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="reactions")
    post = relationship("Post", back_populates="reactions")


# ── Poll ─────────────────────────────────────────────────────────────────────
class Poll(Base):
    __tablename__ = "polls"

    id         = Column(Integer, primary_key=True, index=True)
    post_id    = Column(Integer, ForeignKey("posts.id"), nullable=False)
    question   = Column(String(300), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    post    = relationship("Post", back_populates="poll")
    options = relationship("PollOption", back_populates="poll", cascade="all, delete")


class PollOption(Base):
    __tablename__ = "poll_options"

    id      = Column(Integer, primary_key=True, index=True)
    poll_id = Column(Integer, ForeignKey("polls.id"), nullable=False)
    text    = Column(String(200), nullable=False)

    poll  = relationship("Poll", back_populates="options")
    votes = relationship("PollVote", back_populates="option", cascade="all, delete")


class PollVote(Base):
    __tablename__ = "poll_votes"

    id        = Column(Integer, primary_key=True, index=True)
    option_id = Column(Integer, ForeignKey("poll_options.id"), nullable=False)
    user_id   = Column(Integer, ForeignKey("users.id"), nullable=False)
    voted_at  = Column(DateTime(timezone=True), server_default=func.now())

    option = relationship("PollOption", back_populates="votes")
    user   = relationship("User")


# ── ML Feature Store ─────────────────────────────────────────────────────────
class UserFeature(Base):
    """Cached user-level ML features (recomputed by pipeline)."""
    __tablename__ = "user_features"

    id              = Column(Integer, primary_key=True, index=True)
    user_id         = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False)
    pagerank        = Column(Float, default=0.0)
    community_id    = Column(Integer, nullable=True)
    graph_degree    = Column(Integer, default=0)
    topic_vector    = Column(JSON, nullable=True)       # NMF topic distribution
    interest_embedding = Column(JSON, nullable=True)    # reduced interest vector
    engagement_rate = Column(Float, default=0.0)
    activity_level  = Column(Float, default=0.0)
    updated_at      = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user = relationship("User")


class PostFeature(Base):
    """Cached post-level ML features."""
    __tablename__ = "post_features"

    id             = Column(Integer, primary_key=True, index=True)
    post_id        = Column(Integer, ForeignKey("posts.id"), unique=True, nullable=False)
    topic_vector   = Column(JSON, nullable=True)
    tfidf_norm     = Column(Float, default=0.0)
    toxicity_score = Column(Float, default=0.0)
    updated_at     = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    post = relationship("Post")


class PeopleScore(Base):
    """ML-scored stranger recommendations per user."""
    __tablename__ = "people_scores"

    id         = Column(Integer, primary_key=True, index=True)
    user_id    = Column(Integer, ForeignKey("users.id"), nullable=False)
    target_id  = Column(Integer, ForeignKey("users.id"), nullable=False)
    score      = Column(Float, default=0.0)
    breakdown  = Column(JSON, nullable=True)   # {"jaccard": 0.3, "fof": 0.2, ...}
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user   = relationship("User", foreign_keys=[user_id])
    target = relationship("User", foreign_keys=[target_id])


class ZoneScore(Base):
    """ML-scored zone recommendations per user."""
    __tablename__ = "zone_scores"

    id         = Column(Integer, primary_key=True, index=True)
    user_id    = Column(Integer, ForeignKey("users.id"), nullable=False)
    zone_id    = Column(Integer, ForeignKey("zones.id"), nullable=False)
    score      = Column(Float, default=0.0)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user = relationship("User")
    zone = relationship("Zone")


class ContentFlag(Base):
    """Safety flagging log from ML pipeline."""
    __tablename__ = "content_flags"

    id         = Column(Integer, primary_key=True, index=True)
    post_id    = Column(Integer, ForeignKey("posts.id"), nullable=False)
    flag_type  = Column(String(30), nullable=False)   # toxicity, spam, bot
    confidence = Column(Float, default=0.0)
    flagged_at = Column(DateTime(timezone=True), server_default=func.now())

    post = relationship("Post")


class PipelineRun(Base):
    """ML pipeline execution history."""
    __tablename__ = "pipeline_runs"

    id           = Column(Integer, primary_key=True, index=True)
    status       = Column(String(20), default="pending")   # pending, running, success, failed
    steps_completed = Column(Integer, default=0)
    total_steps  = Column(Integer, default=7)
    duration_sec = Column(Float, nullable=True)
    error_msg    = Column(Text, nullable=True)
    triggered_by = Column(String(50), nullable=True)  # 'manual', 'scheduler', 'api'
    started_at   = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)
