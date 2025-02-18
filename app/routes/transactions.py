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
@router.post("/assign-credit")
def assign_credit(request: CreditAssignRequest, Authorize: AuthJWT = Depends(), db: Session = Depends(get_db)):
    Authorize.jwt_required()  # ✅ Verifica il token direttamente
    user_email = Authorize.get_jwt_subject()
    
    print(f"🔍 DEBUG: Token valido, utente autenticato: {user_email}")

    user = db.query(User).filter(User.email == user_email).first()
    if not user or user.role != "superadmin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Accesso negato")

    admin = db.query(User).filter(User.email == request.admin_email, User.role == "admin").first()
    if not admin:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Admin non trovato")

    admin.credit += request.amount
    db.commit()
    db.refresh(admin)

    return {"message": f"Credito assegnato con successo. Nuovo saldo: {admin.credit}"}
    
@router.post("/use-credit")
def use_credit(amount: float, Authorize: AuthJWT = Depends(), db: Session = Depends(get_db)):
    Authorize.jwt_required()  # ✅ Verifica il token direttamente
    user_email = Authorize.get_jwt_subject()

    print(f"🔍 DEBUG: Token valido, utente autenticato: {user_email}")

    user = db.query(User).filter(User.email == user_email).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Utente non trovato")

    if user.credit < amount:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Credito insufficiente")

    user.credit -= amount
    db.commit()
    db.refresh(user)

    return {"message": f"Credito scalato: {amount}. Credito rimanente: {user.credit}"}

