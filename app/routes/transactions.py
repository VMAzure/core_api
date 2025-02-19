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
def use_credit(amount: float, target_email: str = None, Authorize: AuthJWT = Depends(), db: Session = Depends(get_db)):
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()

    print(f"🔍 DEBUG: Token valido, utente autenticato: {user_email}")

    requesting_user = db.query(User).filter(User.email == user_email).first()
    if not requesting_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Utente autenticato non trovato")

    # Se l'utente è Super Admin, può scegliere un altro utente a cui togliere credito
    if requesting_user.role == "superadmin" and target_email:
        target_user = db.query(User).filter(User.email == target_email).first()
        if not target_user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Utente target non trovato")
    else:
        # Se non è Super Admin, può solo scalare credito a sé stesso
        target_user = requesting_user

    if target_user.credit < amount:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Credito insufficiente")

    target_user.credit -= amount
    db.commit()
    db.refresh(target_user)

    return {
        "message": f"Credito scalato: {amount}. Nuovo saldo: {target_user.credit}",
        "user": target_user.email
    }

