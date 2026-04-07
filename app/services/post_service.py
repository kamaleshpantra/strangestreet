import os
import uuid
import shutil
from sqlalchemy.orm import Session, joinedload
from fastapi import UploadFile, HTTPException
from app.models import Post, Comment, InteractionLog, Reaction, Bookmark, Poll, PollOption, PollVote, Notification, post_likes, PostFeature, ContentFlag

UPLOAD_DIR = "app/static/uploads/posts"
ALLOWED_EXT = {
    ".jpg",".jpeg",".png",".gif",".webp",".avif",".bmp",".tiff",".svg",".ico",
    ".mp4",".webm",".ogg",".mov",".avi",".mkv",".m4v",".3gp",".flv",".wmv",
}
VIDEO_EXT = {".mp4",".webm",".ogg",".mov",".avi",".mkv",".m4v",".3gp",".flv",".wmv"}
ACTION_WEIGHTS = {"view":0.1,"like":1.0,"comment":2.0,"share":3.0,"skip":-0.5}

def log_interaction(db: Session, user_id: int, post_id: int, action: str):
    db.add(InteractionLog(
        user_id=user_id, post_id=post_id,
        action=action, weight=ACTION_WEIGHTS.get(action, 0.0),
    ))
    db.commit()

class PostService:
    @staticmethod
    def create_post(
        db: Session, user_id: int, content: str, category: str, 
        zone_id: int = None, poll_question: str = "", poll_options: list = [],
        media: UploadFile = None
    ) -> Post:
        media_url = None
        media_type = None

        if media and media.filename:
            from app.services.cloudinary_service import CloudinaryService
            from config import settings
            
            ext = os.path.splitext(media.filename)[1].lower()
            is_video = ext in VIDEO_EXT
            
            # 1. Try Cloudinary
            if settings.CLOUDINARY_CLOUD_NAME:
                media_url = CloudinaryService.upload_image(media.file, folder="strangestreet/posts")
                if media_url:
                    media_type = "video" if is_video else "image"
            
            # 2. Fallback to Local
            if not media_url:
                if is_video:
                    fname = f"{uuid.uuid4().hex}{ext}"
                    os.makedirs(UPLOAD_DIR, exist_ok=True)
                    fpath = os.path.join(UPLOAD_DIR, fname)
                    with open(fpath, "wb") as f:
                        shutil.copyfileobj(media.file, f)
                else:
                    from app.utils import compress_image
                    fname = compress_image(media, UPLOAD_DIR, max_size=(1600, 1600))
                    if not fname:
                        fname = f"{uuid.uuid4().hex}{ext}"
                        os.makedirs(UPLOAD_DIR, exist_ok=True)
                        fpath = os.path.join(UPLOAD_DIR, fname)
                        with open(fpath, "wb") as f:
                            shutil.copyfileobj(media.file, f)
                
                media_url = f"/static/uploads/posts/{fname}"
                media_type = "video" if is_video else "image"

        post = Post(
            content=content,
            category=category,
            user_id=user_id,
            image_url=media_url,
            media_type=media_type,
            zone_id=zone_id,
        )
        db.add(post)
        db.flush()

        # Create poll if provided
        if poll_question and len(poll_options) >= 2:
            poll = Poll(post_id=post.id, question=poll_question)
            db.add(poll)
            db.flush()
            for opt_text in poll_options:
                db.add(PollOption(poll_id=poll.id, text=opt_text))

        db.commit()
        db.refresh(post)
        return post

    @staticmethod
    def delete_post(db: Session, post_id: int, user_id: int) -> bool:
        post = db.query(Post).filter(Post.id == post_id).first()
        if not post:
            return False
        if post.user_id != user_id:
            # Check if user is admin (optional, for safety)
            from app.models import User
            user = db.query(User).filter(User.id == user_id).first()
            if not user or not (getattr(user, 'is_admin', False)):
                return False

        # Clean up media file
        try:
            if post.image_url:
                if post.image_url.startswith("/static/uploads/posts/"):
                    # Local file
                    fpath = os.path.join("app", post.image_url.lstrip("/"))
                    if os.path.exists(fpath):
                        os.remove(fpath)
                elif "res.cloudinary.com" in post.image_url:
                    # Cloudinary file
                    from app.services.cloudinary_service import CloudinaryService
                    public_id = CloudinaryService.get_public_id(post.image_url)
                    if public_id:
                        CloudinaryService.delete_image(public_id)
        except Exception as e:
            print(f"[PostService] Error cleaning up media: {e}")

        # Clean up non-cascaded dependencies
        from app.models import InteractionLog, FeedScore, PostFeature, ContentFlag, Notification
        
        try:
            db.query(InteractionLog).filter(InteractionLog.post_id == post_id).delete()
            db.query(FeedScore).filter(FeedScore.post_id == post_id).delete()
            db.query(PostFeature).filter(PostFeature.post_id == post_id).delete()
            db.query(ContentFlag).filter(ContentFlag.post_id == post_id).delete()
            
            # Clear Notifications linked to this post
            db.query(Notification).filter(
                Notification.reference_id == post_id,
                Notification.reference_type == "post",
            ).delete()
            
            db.delete(post)
            db.commit()
            return True
        except Exception as e:
            db.rollback()
            print(f"[PostService] Error deleting post {post_id}: {e}")
            return False

