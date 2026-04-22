"""
Centralized constants for the Strange Street application.
All shared constants should live here to avoid duplication across routers and services.
"""

# ── File Upload Constants ─────────────────────────────────────────────────────
ALLOWED_IMAGE_EXT = {
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif", ".bmp", ".tiff", ".svg", ".ico",
}

ALLOWED_VIDEO_EXT = {
    ".mp4", ".webm", ".ogg", ".mov", ".avi", ".mkv", ".m4v", ".3gp", ".flv", ".wmv",
}

ALLOWED_FILE_EXT = {
    ".pdf", ".doc", ".docx", ".zip", ".txt",
}

# Combined set for post uploads (images + videos)
ALLOWED_POST_EXT = ALLOWED_IMAGE_EXT | ALLOWED_VIDEO_EXT

# Combined set for message uploads (images + videos + documents)
ALLOWED_MSG_EXT = ALLOWED_IMAGE_EXT | ALLOWED_VIDEO_EXT | ALLOWED_FILE_EXT

# Upload directories
UPLOAD_DIR_POSTS    = "app/static/uploads/posts"
UPLOAD_DIR_AVATARS  = "app/static/uploads/avatars"
UPLOAD_DIR_ZONES    = "app/static/uploads/zones"
UPLOAD_DIR_STORIES  = "app/static/uploads/stories"
UPLOAD_DIR_MESSAGES = "app/static/uploads/messages"


# ── Post Categories ───────────────────────────────────────────────────────────
CATEGORIES = [
    "general", "technology", "sports", "news", "science",
    "gaming", "food", "travel", "music", "art",
]


# ── ML Interaction Weights ────────────────────────────────────────────────────
ACTION_WEIGHTS = {
    "view": 0.1,
    "like": 1.0,
    "comment": 2.0,
    "share": 3.0,
    "skip": -0.5,
}


# ── Reaction Emojis ──────────────────────────────────────────────────────────
REACTION_EMOJIS = {
    "fire": "🔥",
    "love": "❤️",
    "laugh": "😂",
    "mind_blown": "🤯",
    "clap": "👏",
    "dead": "💀",
}
