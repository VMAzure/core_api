﻿from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from fastapi_jwt_auth import AuthJWT
from app.database import SessionLocal  # Importiamo solo SessionLocal
from app.models import Services, PurchasedServices, User
from pydantic import BaseModel
import logging

# Configura i log
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

marketplace_router = APIRouter(prefix="/marketplace", tags=["Marketplace"])

# Funzione get_db come in auth.py
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

class ServiceCreate(BaseModel):
    name: str
    description: str
    price: float

@marketplace_router.post("/services")
def add_service(service: ServiceCreate, Authorize: AuthJWT = Depends(), db: Session = Depends(get_db)):
    Authorize.jwt_required()
    user_id = Authorize.get_jwt_subject()
    
    logger.info(f"✅ [DEBUG] - Utente autenticato con ID: {user_id}")

    user = db.query(User).filter(User.id == user_id).first()
    if not user or user.role != 'superadmin':
        raise HTTPException(status_code=403, detail="Accesso negato")

    logger.info("✅ [DEBUG] - Utente verificato come Super Admin, procediamo con la creazione del servizio")

    try:
        new_service = Services(name=service.name, description=service.description, price=service.price)
        db.add(new_service)
        db.commit()
        db.refresh(new_service)
        
        logger.info(f"✅ [SUCCESSO] - Servizio creato con successo: ID {new_service.id}")
        
        return {"message": "Servizio aggiunto con successo", "service_id": new_service.id}

    except Exception as e:
        db.rollback()
        logger.error(f"❌ [ERRORE] - Errore nel salvataggio: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Errore nel salvataggio: {str(e)}")


