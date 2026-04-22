from fastapi import APIRouter, Depends, Request, Form, HTTPException
import re
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from database import get_db
from app.models import User, Interest
from app.auth import hash_password, verify_password, create_access_token, get_current_user
from app.services.bloom_service import bloom_service
from fastapi import Query
from config import settings

router = APIRouter(prefix="/auth", tags=["auth"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/register", response_class=HTMLResponse)
def register_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if user:
        return RedirectResponse("/", status_code=302)

    # Get interests grouped by category
    interests = db.query(Interest).order_by(Interest.category, Interest.name).all()
    categories = {}
    for i in interests:
        if i.category not in categories:
            categories[i.category] = []
        categories[i.category].append(i)

    return templates.TemplateResponse("register.html", {
        "request": request, "categories": categories,
    })


@router.get("/check-availability")
def check_availability(
    type: str = Query(...), 
    value: str = Query(...),
    db: Session = Depends(get_db)
):
    """Real-time bloom filter check for username/email availability."""
    value = value.strip().lower()
    
    if type == "username":
        if not bloom_service.might_username_exist(value):
            return {"available": True} # Definitely not taken
        # Potential false positive, double-check database
        exists = db.query(User).filter(User.username.ilike(value)).first() is not None
        return {"available": not exists}
        
    elif type == "email":
        if not bloom_service.might_email_exist(value):
            return {"available": True}
        exists = db.query(User).filter(User.email.ilike(value)).first() is not None
        return {"available": not exists}

    elif type == "alias":
        if not bloom_service.might_alias_exist(value):
            return {"available": True}
        exists = db.query(User).filter(User.alias_name.ilike(value)).first() is not None
        return {"available": not exists}
        
    return {"available": False}


@router.post("/register")
def register(
    request: Request,
    username: str     = Form(...),
    email: str        = Form(...),
    password: str     = Form(...),
    confirm_password: str = Form(...),
    display_name: str = Form(""),
    bio: str          = Form(""),
    relationship_status: str = Form(""),
    alias_name: str = Form(""),
    alias_bio: str = Form(""),
    alias_relationship_status: str = Form(""),
    interest_ids: str = Form(""),  # comma-separated
    db: Session       = Depends(get_db),
):
    # Get interests for re-rendering on error
    all_interests = db.query(Interest).order_by(Interest.category, Interest.name).all()
    categories = {}
    for i in all_interests:
        if i.category not in categories:
            categories[i.category] = []
        categories[i.category].append(i)

    # Validate passwords match
    if password != confirm_password:
        return templates.TemplateResponse("register.html", {
            "request": request, "error": "Passwords do not match.", "categories": categories,
        })

    # Check duplicates
    if db.query(User).filter(User.username == username).first():
        return templates.TemplateResponse("register.html", {
            "request": request, "error": "Username already taken.", "categories": categories,
        })
    if db.query(User).filter(User.email == email).first():
        return templates.TemplateResponse("register.html", {
            "request": request, "error": "Email already registered.", "categories": categories,
        })
    if alias_name and db.query(User).filter(User.alias_name.ilike(alias_name)).first():
        return templates.TemplateResponse("register.html", {
            "request": request, "error": "Alias name already taken.", "categories": categories,
        })
    if not alias_name:
        return templates.TemplateResponse("register.html", {
            "request": request, "error": "Alias name is required.", "categories": categories,
        })
    
    # Regex validation for alphanumeric + underscore
    pattern = re.compile(r"^[a-zA-Z0-9_]+$")
    if not pattern.match(username):
        return templates.TemplateResponse("register.html", {
            "request": request, "error": "Username can only contain letters, numbers, and underscores.", "categories": categories,
        })
    if not pattern.match(alias_name):
        return templates.TemplateResponse("register.html", {
            "request": request, "error": "Alias name can only contain letters, numbers, and underscores.", "categories": categories,
        })

    user = User(
        username=username,
        email=email,
        hashed_password=hash_password(password),
        display_name=display_name or username,
        bio=bio,
        relationship_status=relationship_status or None,
        alias_name=alias_name,
        alias_bio=alias_bio or None,
        alias_relationship_status=alias_relationship_status or None,
    )
    db.add(user)
    db.flush()

    # Add interests
    if interest_ids:
        ids = [int(x) for x in interest_ids.split(",") if x.strip().isdigit()]
        interests = db.query(Interest).filter(Interest.id.in_(ids)).all()
        user.interests = interests

    db.commit()
    db.refresh(user)

    # Sync bloom filter
    bloom_service.add_user(user.username, user.email, user.alias_name)

    token = create_access_token({"sub": user.username})
    response = RedirectResponse("/", status_code=302)
    response.set_cookie("access_token", token, httponly=True, max_age=604800, secure=not settings.DEBUG, samesite="lax")
    return response


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if user:
        return RedirectResponse("/", status_code=302)
    return templates.TemplateResponse("login.html", {"request": request})


@router.post("/login")
def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session   = Depends(get_db),
):
    user = db.query(User).filter(User.username == username).first()
    if not user or not verify_password(password, user.hashed_password):
        return templates.TemplateResponse("login.html", {
            "request": request, "error": "Invalid username or password."
        })

    token = create_access_token({"sub": user.username})
    response = RedirectResponse("/", status_code=302)
    response.set_cookie("access_token", token, httponly=True, max_age=604800, secure=not settings.DEBUG, samesite="lax")
    return response


@router.get("/logout")
def logout():
    response = RedirectResponse("/auth/login", status_code=302)
    response.delete_cookie("access_token")
    return response
