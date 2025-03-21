from fastapi import APIRouter, Depends, HTTPException
from fastapi_jwt_auth import AuthJWT
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import User

router = APIRouter()

@router.get("/ping", tags=["AZLease"])
async def ping_azlease(Authorize: AuthJWT = Depends(), db: Session = Depends(get_db)):
    """Ping protetto per verificare se il modulo azlease è attivo"""
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()

    user = db.query(User).filter(User.email == user_email).first()
    if not user:
        raise HTTPException(status_code=401, detail="Utente non trovato")

    return {"message": "AZLease è attivo!", "utente": user.email}
