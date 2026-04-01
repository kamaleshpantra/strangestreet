from fastapi import APIRouter, Depends, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from database import get_db
from app.models import User
from app.auth import require_login

router = APIRouter(prefix="/economy", tags=["economy"])
templates = Jinja2Templates(directory="app/templates")

@router.get("", response_class=HTMLResponse)
def economy_dashboard(request: Request, db: Session = Depends(get_db)):
    user = require_login(request, db)
    return templates.TemplateResponse("economy.html", {
        "request": request, "user": user
    })

@router.post("/subscribe-premium")
def subscribe_premium(request: Request, db: Session = Depends(get_db)):
    user = require_login(request, db)
    # Simulator: In a real app this hits Stripe/PayPal
    user.is_premium = True
    db.commit()
    return RedirectResponse("/economy?success=premium", status_code=302)

@router.post("/buy-coins")
def buy_coins(request: Request, amount: int = Form(...), db: Session = Depends(get_db)):
    user = require_login(request, db)
    # Simulator: Add coins assuming payment succeeded
    if amount not in [100, 500, 1000]:
        raise HTTPException(status_code=400, detail="Invalid coin package")
    
    user.street_coins += amount
    db.commit()
    return RedirectResponse("/economy?success=coins", status_code=302)
