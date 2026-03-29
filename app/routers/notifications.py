from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import desc
from database import get_db
from app.models import Notification
from app.auth import require_login, get_current_user

router = APIRouter(prefix="/notifications", tags=["notifications"])
templates = Jinja2Templates(directory="app/templates")


@router.get("", response_class=HTMLResponse)
def notifications_page(request: Request, db: Session = Depends(get_db)):
    user = require_login(request, db)

    notifs = db.query(Notification).filter(
        Notification.user_id == user.id,
    ).order_by(desc(Notification.created_at)).limit(100).all()

    # Mark all as read
    db.query(Notification).filter(
        Notification.user_id == user.id,
        Notification.is_read == False,
    ).update({"is_read": True})
    db.commit()

    return templates.TemplateResponse("notifications.html", {
        "request": request, "user": user, "notifications": notifs,
    })


@router.get("/count")
def unread_count(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return JSONResponse({"count": 0})

    from app.models import Message
    notif_count = db.query(Notification).filter(
        Notification.user_id == user.id,
        Notification.is_read == False,
    ).count()

    msg_count = db.query(Message).filter(
        Message.receiver_id == user.id,
        Message.is_read == False,
    ).count()

    return JSONResponse({"count": notif_count, "messages": msg_count})


@router.post("/read-all")
def read_all(request: Request, db: Session = Depends(get_db)):
    user = require_login(request, db)
    db.query(Notification).filter(
        Notification.user_id == user.id,
        Notification.is_read == False,
    ).update({"is_read": True})
    db.commit()
    return JSONResponse({"ok": True})
