from fastapi import APIRouter, Depends, Request, Form, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, desc
from database import get_db
from app.models import User, Message, Connection, Reveal, Notification
from app.auth import require_login
from app.services.encryption_service import cipher
import shutil, os, uuid

router = APIRouter(prefix="/messages", tags=["messages"])
templates = Jinja2Templates(directory="app/templates")

MSG_UPLOAD_DIR = "app/static/uploads/messages"
ALLOWED_EXT = {
    ".jpg",".jpeg",".png",".gif",".webp",".avif",".bmp",".svg",
    ".mp4",".webm",".mov",".pdf",".doc",".docx",".zip",".txt"
}
VIDEO_EXT = {".mp4",".webm",".mov"}
IMAGE_EXT = {".jpg",".jpeg",".png",".gif",".webp",".avif",".bmp"}


@router.get("", response_class=HTMLResponse)
def inbox(request: Request, db: Session = Depends(get_db)):
    user = require_login(request, db)

    # Alias conversations (via connections)
    active_connections = db.query(Connection).filter(
        or_(
            Connection.requester_id == user.id,
            Connection.requested_id == user.id,
        ),
        Connection.status == "accepted",
    ).all()

    alias_convos = []
    for conn in active_connections:
        other = conn.requested if conn.requester_id == user.id else conn.requester
        last_msg = db.query(Message).filter(
            Message.connection_id == conn.id,
        ).order_by(desc(Message.created_at)).first()

        unread = db.query(Message).filter(
            Message.connection_id == conn.id,
            Message.receiver_id == user.id,
            Message.is_read == False,
        ).count()

        # Reveal levels
        other_reveal = next((r for r in conn.reveals if r.user_id == other.id), None)
        my_reveal = next((r for r in conn.reveals if r.user_id == user.id), None)

        if last_msg:
            last_msg.content = cipher.decrypt(last_msg.content)

        alias_convos.append({
            "connection": conn,
            "other": other,
            "last_message": last_msg,
            "unread": unread,
            "other_reveal_level": other_reveal.level if other_reveal else 0,
            "my_reveal_level": my_reveal.level if my_reveal else 0,
        })

    # Sort by last message
    alias_convos.sort(key=lambda x: x["last_message"].created_at if x["last_message"] else x["connection"].created_at, reverse=True)

    # Public DM conversations
    # Find unique users I've had public DMs with
    public_msgs = db.query(Message).filter(
        Message.connection_id.is_(None),
        or_(Message.sender_id == user.id, Message.receiver_id == user.id),
    ).order_by(desc(Message.created_at)).all()

    public_convos = {}
    for msg in public_msgs:
        other_id = msg.receiver_id if msg.sender_id == user.id else msg.sender_id
        if other_id not in public_convos:
            other_user = db.query(User).filter(User.id == other_id).first()
            unread = db.query(Message).filter(
                Message.connection_id.is_(None),
                Message.sender_id == other_id,
                Message.receiver_id == user.id,
                Message.is_read == False,
            ).count()
            if msg:
                msg.content = cipher.decrypt(msg.content)
            public_convos[other_id] = {
                "other": other_user,
                "last_message": msg,
                "unread": unread,
            }

    return templates.TemplateResponse("messages.html", {
        "request": request, "user": user,
        "alias_convos": alias_convos,
        "public_convos": list(public_convos.values()),
    })


@router.get("/c/{connection_id}", response_class=HTMLResponse)
def alias_chat(connection_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_login(request, db)

    conn = db.query(Connection).filter(
        Connection.id == connection_id,
        Connection.status == "accepted",
        or_(Connection.requester_id == user.id, Connection.requested_id == user.id),
    ).first()

    if not conn:
        raise HTTPException(status_code=404)

    other = conn.requested if conn.requester_id == user.id else conn.requester

    # Mark messages as read
    db.query(Message).filter(
        Message.connection_id == connection_id,
        Message.receiver_id == user.id,
        Message.is_read == False,
    ).update({"is_read": True})
    db.commit()

    messages = db.query(Message).filter(
        Message.connection_id == connection_id,
    ).order_by(Message.created_at).all()

    for msg in messages:
        msg.content = cipher.decrypt(msg.content)

    # Reveal info
    other_reveal = next((r for r in conn.reveals if r.user_id == other.id), None)
    my_reveal = next((r for r in conn.reveals if r.user_id == user.id), None)

    return templates.TemplateResponse("chat.html", {
        "request": request, "user": user, "other": other,
        "connection": conn, "messages": messages,
        "other_reveal_level": other_reveal.level if other_reveal else 0,
        "my_reveal_level": my_reveal.level if my_reveal else 0,
        "is_alias": True,
    })


def handle_msg_upload(media: UploadFile):
    if not media or not media.filename:
        return None, None, None
        
    ext = os.path.splitext(media.filename)[1].lower()
    if ext not in ALLOWED_EXT:
        ext = ".bin"
        
    is_video = ext in VIDEO_EXT
    is_image = ext in IMAGE_EXT
    
    media_type = "video" if is_video else ("image" if is_image else "file")
    os.makedirs(MSG_UPLOAD_DIR, exist_ok=True)
    
    if is_image:
        from app.utils import compress_image
        fname = compress_image(media, MSG_UPLOAD_DIR, prefix="msg_", max_size=(1600,1600))
        if not fname: # fallback
            fname = f"msg_{uuid.uuid4().hex}{ext}"
            with open(os.path.join(MSG_UPLOAD_DIR, fname), "wb") as f:
                shutil.copyfileobj(media.file, f)
    else:
        fname = f"msg_{uuid.uuid4().hex}{ext}"
        with open(os.path.join(MSG_UPLOAD_DIR, fname), "wb") as f:
            shutil.copyfileobj(media.file, f)
            
    return f"/static/uploads/messages/{fname}", media_type, media.filename


@router.post("/c/{connection_id}/send")
def send_alias_message(
    connection_id: int, request: Request,
    content: str = Form(""),
    media: UploadFile = File(None),
    db: Session = Depends(get_db),
):
    user = require_login(request, db)

    conn = db.query(Connection).filter(
        Connection.id == connection_id,
        Connection.status == "accepted",
        or_(Connection.requester_id == user.id, Connection.requested_id == user.id),
    ).first()

    if not conn:
        raise HTTPException(status_code=404)

    other_id = conn.requested_id if conn.requester_id == user.id else conn.requester_id
    
    media_url, media_type, file_name = handle_msg_upload(media)
    final_content = content.strip() or ("📎 Attachment" if media_url else "")
    if not final_content and not media_url:
        return RedirectResponse(f"/messages/c/{connection_id}", status_code=302)

    msg = Message(
        sender_id=user.id, receiver_id=other_id,
        connection_id=connection_id, content=cipher.encrypt(final_content),
        media_url=media_url, media_type=media_type, file_name=file_name
    )
    db.add(msg)

    # Notify
    db.add(Notification(
        user_id=other_id, actor_id=user.id,
        type="message", reference_id=connection_id, reference_type="connection",
        message="You have a new message from a connection",
    ))
    db.commit()

    return RedirectResponse(f"/messages/c/{connection_id}", status_code=302)


@router.get("/public/{username}", response_class=HTMLResponse)
def public_chat(username: str, request: Request, db: Session = Depends(get_db)):
    user = require_login(request, db)

    other = db.query(User).filter(User.username == username).first()
    if not other or other.id == user.id:
        raise HTTPException(status_code=404)

    # Mark messages as read
    db.query(Message).filter(
        Message.connection_id.is_(None),
        Message.sender_id == other.id,
        Message.receiver_id == user.id,
        Message.is_read == False,
    ).update({"is_read": True})
    db.commit()

    messages = db.query(Message).filter(
        Message.connection_id.is_(None),
        or_(
            and_(Message.sender_id == user.id, Message.receiver_id == other.id),
            and_(Message.sender_id == other.id, Message.receiver_id == user.id),
        ),
    ).order_by(Message.created_at).all()

    for msg in messages:
        msg.content = cipher.decrypt(msg.content)

    return templates.TemplateResponse("chat.html", {
        "request": request, "user": user, "other": other,
        "connection": None, "messages": messages,
        "other_reveal_level": 3, "my_reveal_level": 3,
        "is_alias": False,
    })


@router.post("/public/{username}/send")
def send_public_message(
    username: str, request: Request,
    content: str = Form(""),
    media: UploadFile = File(None),
    db: Session = Depends(get_db),
):
    user = require_login(request, db)

    other = db.query(User).filter(User.username == username).first()
    if not other or other.id == user.id:
        raise HTTPException(status_code=404)
        
    media_url, media_type, file_name = handle_msg_upload(media)
    final_content = content.strip() or ("📎 Attachment" if media_url else "")
    if not final_content and not media_url:
        return RedirectResponse(f"/messages/public/{username}", status_code=302)

    msg = Message(
        sender_id=user.id, receiver_id=other.id,
        connection_id=None, content=cipher.encrypt(final_content),
        media_url=media_url, media_type=media_type, file_name=file_name
    )
    db.add(msg)

    db.add(Notification(
        user_id=other.id, actor_id=user.id,
        type="message", reference_id=user.id, reference_type="user",
        message=f"{user.display_name} sent you a message",
    ))
    db.commit()

    return RedirectResponse(f"/messages/public/{username}", status_code=302)


@router.post("/{msg_id}/delete")
def delete_message(msg_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_login(request, db)
    
    msg = db.query(Message).filter(Message.id == msg_id, Message.sender_id == user.id).first()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found or you don't have permission")
        
    db.delete(msg)
    db.commit()
    return JSONResponse({"success": True})
