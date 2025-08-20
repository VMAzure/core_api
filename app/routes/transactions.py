from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models import User
from fastapi_jwt_auth import AuthJWT  # ✅ Importiamo AuthJWT
from pydantic import BaseModel
from app.auth_helpers import get_dealer_id


router = APIRouter()

# Modello per assegnare credito
class CreditAssignRequest(BaseModel):
    admin_email: str
    amount: float

# Funzione per ottenere il database
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Endpoint per assegnare credito (solo Super Admin)
from app.auth_helpers import get_admin_id

@router.post("/assign-credit")
def assign_credit(request: CreditAssignRequest, Authorize: AuthJWT = Depends(), db: Session = Depends(get_db)):
    """
    Ricarica credito manualmente sull’admin. Solo l’admin è autorizzato.
    """
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()

    user = db.query(User).filter(User.email == user_email).first()
    if not user or user.role != "admin":
        raise HTTPException(status_code=403, detail="Accesso negato: solo l'admin può assegnare credito.")

    # Carica se stesso
    admin = db.query(User).filter(User.email == request.admin_email, User.role == "admin").first()
    if not admin:
        raise HTTPException(status_code=404, detail="Admin non trovato")

    admin.credit += request.amount
    db.commit()
    db.refresh(admin)

    return {"message": f"Credito assegnato. Nuovo saldo: {admin.credit}"}


@router.post("/use-credit")
def use_credit(amount: float, Authorize: AuthJWT = Depends(), db: Session = Depends(get_db)):
    """
    Scarica credito al dealer loggato. Usato da cronjob o azioni automatiche.
    """
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()

    user = db.query(User).filter(User.email == user_email).first()
    if not user or user.role not in ["dealer", "dealer_team"]:
        raise HTTPException(status_code=403, detail="Accesso negato: solo il dealer può utilizzare credito.")

    dealer_id = get_dealer_id(user)
    dealer = db.query(User).filter(User.id == dealer_id, User.role == "dealer").first()
    if not dealer:
        raise HTTPException(status_code=404, detail="Dealer principale non trovato")

    if dealer.credit < amount:
        raise HTTPException(status_code=400, detail="Credito insufficiente")

    dealer.credit -= amount
    db.commit()
    db.refresh(dealer)

    return {
        "message": f"Credito scalato: {amount}. Nuovo saldo: {dealer.credit}",
        "dealer": dealer.email
    }



