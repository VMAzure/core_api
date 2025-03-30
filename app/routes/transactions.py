from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models import User
from fastapi_jwt_auth import AuthJWT  # ✅ Importiamo AuthJWT
from pydantic import BaseModel

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
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()

    user = db.query(User).filter(User.email == user_email).first()
    if not user or user.role != "superadmin":
        raise HTTPException(status_code=403, detail="Accesso negato")

    # Trova l'utente a cui vogliamo assegnare (potrebbe essere admin_team)
    target_user = db.query(User).filter(User.email == request.admin_email).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="Utente non trovato")

    # Recupera l'admin effettivo
    admin_id = get_admin_id(target_user)
    admin = db.query(User).filter(User.id == admin_id, User.role == "admin").first()
    if not admin:
        raise HTTPException(status_code=404, detail="Admin principale non trovato")

    admin.credit += request.amount
    db.commit()
    db.refresh(admin)

    return {"message": f"Credito assegnato con successo. Nuovo saldo: {admin.credit}"}

    
@router.post("/use-credit")
def use_credit(amount: float, target_email: str = None, Authorize: AuthJWT = Depends(), db: Session = Depends(get_db)):
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()

    requesting_user = db.query(User).filter(User.email == user_email).first()
    if not requesting_user:
        raise HTTPException(status_code=404, detail="Utente autenticato non trovato")

    # Se superadmin, può specificare a chi scalare credito
    if requesting_user.role == "superadmin" and target_email:
        target_user = db.query(User).filter(User.email == target_email).first()
        if not target_user:
            raise HTTPException(status_code=404, detail="Utente target non trovato")
    else:
        # Altri ruoli: il credito va sempre scalato all'admin principale
        admin_id = get_admin_id(requesting_user)
        target_user = db.query(User).filter(User.id == admin_id, User.role == "admin").first()

        if not target_user:
            raise HTTPException(status_code=404, detail="Admin principale non trovato")

    if target_user.credit < amount:
        raise HTTPException(status_code=400, detail="Credito insufficiente")

    target_user.credit -= amount
    db.commit()
    db.refresh(target_user)

    return {
        "message": f"Credito scalato: {amount}. Nuovo saldo: {target_user.credit}",
        "user": target_user.email
    }


