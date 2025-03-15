from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models import User, PurchasedServices
from fastapi_jwt_auth import AuthJWT
from datetime import datetime, timedelta
from sqlalchemy import text

router = APIRouter()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.get("/days-until-renewal")
def days_until_renewal(Authorize: AuthJWT = Depends(), db: Session = Depends(get_db)):
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()

    user = db.query(User).filter(User.email == user_email).first()

    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Utente non trovato")

    # Recupera il setting della durata del servizio
    setting = db.execute(text("SELECT service_duration_minutes FROM settings")).fetchone()
    default_duration = setting.service_duration_minutes if setting else 43200  # 30 giorni di default

    # Recupera il servizio acquistato più recente dall'utente
    purchased_service = (
        db.query(PurchasedServices)
        .filter(PurchasedServices.admin_id == user.id, PurchasedServices.status == "attivo")
        .order_by(PurchasedServices.activated_at.desc())
        .first()
    )

    if not purchased_service:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Nessun servizio attivo trovato")

    expiration_time = purchased_service.activated_at + timedelta(minutes=default_duration)
    remaining_days = (expiration_time - datetime.utcnow()).days

    return {
        "user": user.email,
        "role": user.role,
        "days_until_renewal": remaining_days if remaining_days >= 0 else 0
    }


