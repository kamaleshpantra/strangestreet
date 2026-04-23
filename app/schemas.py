"""
Pydantic schemas for request/response validation.
These ensure all user input is sanitized and validated before reaching business logic.
"""
from pydantic import BaseModel, Field, field_validator
import re
import html


class PostCreate(BaseModel):
    """Validates post creation input."""
    content: str = Field(..., min_length=1, max_length=5000)
    category: str = Field(default="general", max_length=50)
    zone_id: str = Field(default="")
    poll_question: str = Field(default="", max_length=300)
    poll_options: str = Field(default="", max_length=1000)

    @field_validator("content")
    @classmethod
    def sanitize_content(cls, v: str) -> str:
        return v.strip()

    @field_validator("category")
    @classmethod
    def validate_category(cls, v: str) -> str:
        from app.constants import CATEGORIES
        if v not in CATEGORIES:
            return "general"
        return v


class CommentCreate(BaseModel):
    """Validates comment creation."""
    content: str = Field(..., min_length=1, max_length=2000)
    parent_id: int | None = None

    @field_validator("content")
    @classmethod
    def sanitize_content(cls, v: str) -> str:
        return v.strip()


class MessageCreate(BaseModel):
    """Validates message content."""
    content: str = Field(default="", max_length=5000)


class UserRegister(BaseModel):
    """Validates registration input."""
    username: str = Field(..., min_length=3, max_length=30)
    email: str = Field(..., max_length=255)
    password: str = Field(..., min_length=6, max_length=128)
    display_name: str = Field(..., min_length=1, max_length=100)

    @field_validator("username")
    @classmethod
    def validate_username(cls, v: str) -> str:
        if not re.match(r"^[a-zA-Z0-9_]+$", v):
            raise ValueError("Username can only contain letters, numbers, and underscores")
        return v.lower()

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", v):
            raise ValueError("Invalid email format")
        return v.lower().strip()


class UserLogin(BaseModel):
    """Validates login input."""
    username: str = Field(..., min_length=1, max_length=50)
    password: str = Field(..., min_length=1, max_length=128)
