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
    logger.info("🚀 [DEBUG] - Inizio richiesta su /services")
    
    try:
        logger.info("🔐 [DEBUG] - Verifica autenticazione JWT")
        Authorize.jwt_required()
        logger.info("✅ [DEBUG] - Token JWT verificato con successo")
    except Exception as e:
        logger.error(f"❌ [ERRORE] - JWT non valido: {str(e)}")
        raise HTTPException(status_code=401, detail="Token non valido")

    user_id = Authorize.get_jwt_subject()
    logger.info(f"✅ [DEBUG] - Utente autenticato con ID: {user_id}")

    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            logger.error("❌ [ERRORE] - Utente non trovato nel database")
            raise HTTPException(status_code=404, detail="Utente non trovato")
    except Exception as e:
        logger.error(f"❌ [ERRORE] - Problema nella query dell'utente: {str(e)}")
        raise HTTPException(status_code=500, detail="Errore nel recupero utente")

    if user.role != 'superadmin':
        logger.error(f"❌ [ERRORE] - Accesso negato per l'utente {user_id} con ruolo {user.role}")
        raise HTTPException(status_code=403, detail="Accesso negato")

    logger.info("✅ [DEBUG] - Utente verificato come Super Admin, procediamo con la creazione del servizio")

    try:
        new_service = Services(name=service.name, description=service.description, price=service.price)
        db.add(new_service)
        logger.info("✅ [DEBUG] - Servizio aggiunto al database, prima del commit")

        db.commit()
        db.refresh(new_service)
        logger.info(f"✅ [SUCCESSO] - Servizio creato con successo: ID {new_service.id}")
        
        return {"message": "Servizio aggiunto con successo", "service_id": new_service.id}

    except Exception as e:
        db.rollback()
        logger.error(f"❌ [ERRORE] - Errore nel salvataggio: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Errore nel salvataggio: {str(e)}")


