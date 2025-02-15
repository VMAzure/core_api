from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models import User
from app.routes.auth import get_current_user
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

# Endpoint per usare credito (Admin o Dealer)
@router.post("/use-credit")
def use_credit(amount: float, user_data: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    user = user_data["user"]

    if user.credit < amount:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Credito insufficiente")

    user.credit -= amount
    db.commit()

    return {"message": f"Credito rimosso: {amount}. Credito rimanente: {user.credit}"}

# Endpoint per assegnare credito
@router.post("/assign-credit")
def assign_credit(request: CreditAssignRequest, user_data: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    if user_data["role"] != "superadmin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Accesso negato")

    admin = db.query(User).filter(User.email == request.admin_email, User.role == "admin").first()
    if not admin:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Admin non trovato")

    admin.credit += request.amount
    db.commit()
    db.refresh(admin)

    return {"message": f"Credito assegnato con successo. Nuovo saldo: {admin.credit}"}
