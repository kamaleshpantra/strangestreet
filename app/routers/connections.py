from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from database import get_db
from app.models import User, Connection, Reveal, Notification
from app.auth import require_login

router = APIRouter(prefix="/connections", tags=["connections"])
templates = Jinja2Templates(directory="app/templates")


@router.get("", response_class=HTMLResponse)
def connections_page(request: Request, db: Session = Depends(get_db)):
    user = require_login(request, db)

    # Pending requests received
    pending = db.query(Connection).filter(
        Connection.requested_id == user.id,
        Connection.status == "pending",
    ).all()

    # Pending requests sent
    sent = db.query(Connection).filter(
        Connection.requester_id == user.id,
        Connection.status == "pending",
    ).all()

    # Active connections
    active = db.query(Connection).filter(
        or_(
            Connection.requester_id == user.id,
            Connection.requested_id == user.id,
        ),
        Connection.status == "accepted",
    ).all()

    # Enrich active connections with reveal info
    active_data = []
    for conn in active:
        other = conn.requested if conn.requester_id == user.id else conn.requester
        # What has the other revealed to me?
        other_reveal = next((r for r in conn.reveals if r.user_id == other.id), None)
        my_reveal = next((r for r in conn.reveals if r.user_id == user.id), None)
        active_data.append({
            "connection": conn,
            "other": other,
            "other_reveal_level": other_reveal.level if other_reveal else 0,
            "my_reveal_level": my_reveal.level if my_reveal else 0,
        })

    return templates.TemplateResponse("connections.html", {
        "request": request, "user": user,
        "pending": pending, "sent": sent, "active": active_data,
    })


@router.post("/{user_id}/request")
def send_request(user_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_login(request, db)

    if user_id == user.id:
        raise HTTPException(status_code=400, detail="Cannot connect with yourself")

    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404)

    # Check existing
    existing = db.query(Connection).filter(
        or_(
            and_(Connection.requester_id == user.id, Connection.requested_id == user_id),
            and_(Connection.requester_id == user_id, Connection.requested_id == user.id),
        )
    ).first()

    if existing:
        return JSONResponse({"status": existing.status, "message": "Connection already exists"})

    conn = Connection(requester_id=user.id, requested_id=user_id, status="pending")
    db.add(conn)

    # Notify target
    db.add(Notification(
        user_id=user_id, actor_id=user.id,
        type="connection", reference_id=conn.id, reference_type="connection",
        message=f"Someone wants to connect with you!",
    ))

    db.commit()
    return JSONResponse({"status": "pending", "message": "Connection request sent!"})


@router.post("/{connection_id}/accept")
def accept_connection(connection_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_login(request, db)

    conn = db.query(Connection).filter(
        Connection.id == connection_id,
        Connection.requested_id == user.id,
        Connection.status == "pending",
    ).first()

    if not conn:
        raise HTTPException(status_code=404)

    conn.status = "accepted"

    # Create reveals at level 0 for both users
    db.add(Reveal(connection_id=conn.id, user_id=conn.requester_id, level=0))
    db.add(Reveal(connection_id=conn.id, user_id=conn.requested_id, level=0))

    # Notify requester
    db.add(Notification(
        user_id=conn.requester_id, actor_id=user.id,
        type="connection", reference_id=conn.id, reference_type="connection",
        message=f"Your connection request was accepted!",
    ))

    db.commit()
    return JSONResponse({"status": "accepted"})


@router.post("/{connection_id}/reject")
def reject_connection(connection_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_login(request, db)

    conn = db.query(Connection).filter(
        Connection.id == connection_id,
        Connection.requested_id == user.id,
        Connection.status == "pending",
    ).first()

    if not conn:
        raise HTTPException(status_code=404)

    conn.status = "rejected"
    db.commit()
    return JSONResponse({"status": "rejected"})


@router.post("/{connection_id}/reveal")
def reveal_info(connection_id: int, request: Request, db: Session = Depends(get_db)):
    """Reveal next level of info: 0→1 (bio), 1→2 (username), 2→3 (photo)."""
    user = require_login(request, db)

    conn = db.query(Connection).filter(
        Connection.id == connection_id,
        Connection.status == "accepted",
        or_(Connection.requester_id == user.id, Connection.requested_id == user.id),
    ).first()

    if not conn:
        raise HTTPException(status_code=404)

    reveal = db.query(Reveal).filter(
        Reveal.connection_id == connection_id,
        Reveal.user_id == user.id,
    ).first()

    if not reveal:
        reveal = Reveal(connection_id=connection_id, user_id=user.id, level=0)
        db.add(reveal)

    if reveal.level >= 3:
        return JSONResponse({"level": 3, "message": "Already fully revealed"})

    reveal.level += 1

    # Notify the other person
    other_id = conn.requested_id if conn.requester_id == user.id else conn.requester_id
    level_labels = {1: "their bio", 2: "their username", 3: "their profile photo"}
    db.add(Notification(
        user_id=other_id, actor_id=user.id,
        type="reveal", reference_id=conn.id, reference_type="connection",
        message=f"Someone revealed {level_labels.get(reveal.level, 'info')} to you!",
    ))

    db.commit()
    return JSONResponse({"level": reveal.level, "message": f"Revealed level {reveal.level}"})
