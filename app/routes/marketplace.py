from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from fastapi_jwt_auth import AuthJWT
from app.database import SessionLocal  # Importiamo solo SessionLocal
from app.models import Services, PurchasedServices, User, CreditTransaction  # Importiamo solo i modelli necessari
from pydantic import BaseModel
from sqlalchemy.sql import func, text
import traceback
import sys
import logging

logging.basicConfig(level=logging.DEBUG, handlers=[logging.StreamHandler(sys.stdout)])
logger = logging.getLogger(__name__)
logger.debug("✅ DEBUG: Il logger è attivo e sta funzionando!")

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
    
class AssignServiceRequest(BaseModel):
    admin_email: str = None  # Facoltativo, lo useremo solo se il Super Admin assegna un servizio
    service_id: int

@marketplace_router.post("/services")
def add_service(service: ServiceCreate, Authorize: AuthJWT = Depends(), db: Session = Depends(get_db)):
    print(f"🔍 DEBUG: Token ricevuto: {Authorize._token}")
    Authorize.jwt_required()
    user_id = Authorize.get_jwt_subject()
    
    logger.info(f"✅ [DEBUG] - Utente autenticato con ID: {user_id}")

    user = db.query(User).filter(User.email == user_id).first()
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
        raise HTTPException(status_code=500, detail="Errore nel salvataggio")

@marketplace_router.post("/assign-service")
def assign_service(
    request: AssignServiceRequest, 
    Authorize: AuthJWT = Depends(), 
    db: Session = Depends(get_db)
):
    print("🔍 DEBUG: La funzione assign_service è stata chiamata")
    sys.stdout.flush()

    try:
        Authorize.jwt_required()
        superadmin_email = Authorize.get_jwt_subject()

        # Verifica che l'utente sia un Super Admin
        superadmin = db.query(User).filter(User.email == superadmin_email).first()
        if not superadmin or superadmin.role != "superadmin":
            raise HTTPException(status_code=403, detail="Accesso negato")

        # Verifica che l'Admin esista
        admin = db.query(User).filter(User.email == request.admin_email, User.role == "admin").first()
        if not admin:
            raise HTTPException(status_code=404, detail="Admin non trovato")

        # Verifica che il servizio esista
        service = db.query(Services).filter(Services.id == request.service_id).first()
        if not service:
            raise HTTPException(status_code=404, detail="Servizio non trovato")

        # Controllo credito
        if admin.credit < service.price:
            raise HTTPException(status_code=400, detail="Credito insufficiente per attivare il servizio")

        # Controlla se il servizio è già assegnato
        existing_service = db.query(PurchasedServices).filter(
            PurchasedServices.admin_id == admin.id,
            PurchasedServices.service_id == service.id
        ).first()

        if existing_service:
            existing_service.activated_at = func.now()  # Aggiorna la data di attivazione
            existing_service.status = "attivo"
        else:
            db.add(PurchasedServices(
                admin_id=admin.id, 
                service_id=service.id,
                activated_at=func.now(),
                status="attivo"
            ))

        # Scala il credito e salva la transazione
        admin.credit -= service.price
        db.add(CreditTransaction(
            admin_id=admin.id, amount=-service.price, transaction_type="USE"
        ))

        db.commit()
        db.refresh(admin)

        return {"message": f"Servizio assegnato con successo a {admin.email}, Credito rimanente: {admin.credit}"}

    except Exception as e:
        db.rollback()
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Errore interno: {str(e)}")




@marketplace_router.post("/buy-service")
def buy_service(
    request: AssignServiceRequest, 
    Authorize: AuthJWT = Depends(), 
    db: Session = Depends(get_db)
):
    print("🔍 DEBUG: La funzione buy_service è stata chiamata")
    sys.stdout.flush()

    try:
        Authorize.jwt_required()
        admin_email = Authorize.get_jwt_subject()

        # Verifica che l'utente sia un Admin
        admin = db.query(User).filter(User.email == admin_email, User.role == "admin").first()
        if not admin:
            raise HTTPException(status_code=403, detail="Solo gli Admin possono acquistare servizi")

        # Verifica che il servizio esista
        service = db.query(Services).filter(Services.id == request.service_id).first()
        if not service:
            raise HTTPException(status_code=404, detail="Servizio non trovato")

        # Controlla se l'Admin ha già acquistato questo servizio
        existing_service = db.query(PurchasedServices).filter(
            PurchasedServices.admin_id == admin.id,
            PurchasedServices.service_id == service.id
        ).first()

        if existing_service:
            existing_service.activated_at = func.now()  # Aggiorna la data di attivazione
            existing_service.status = "attivo"
        else:
            db.add(PurchasedServices(
                admin_id=admin.id, 
                service_id=service.id,
                activated_at=func.now(),
                status="attivo"
            ))

        # Controllo del credito
        if admin.credit < service.price:
            raise HTTPException(status_code=400, detail="Credito insufficiente per attivare il servizio")

        # Scala il credito e salva la transazione
        admin.credit -= service.price
        db.add(CreditTransaction(
            admin_id=admin.id, amount=-service.price, transaction_type="USE"
        ))

        db.commit()
        db.refresh(admin)

        return {"message": f"Servizio acquistato con successo, Credito rimanente: {admin.credit}"}

    except Exception as e:
        db.rollback()
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Errore interno: {str(e)}")

@marketplace_router.get("/service-list", response_model=list)
def get_filtered_services(Authorize: AuthJWT = Depends(), db: Session = Depends(get_db)):
    try:
        Authorize.jwt_required()
        user_email = Authorize.get_jwt_subject()
        
        # Verifica se l'utente esiste
        user = db.query(User).filter(User.email == user_email).first()
        if not user:
            raise HTTPException(status_code=403, detail="Accesso negato")
        
        # Recupera tutti i servizi disponibili per tutti gli utenti
        services = db.query(Services).all()
        
        return [{
            "id": service.id,
            "name": service.name,
            "description": service.description,
            "price": service.price
        } for service in services]
        
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Errore interno: {str(e)}")

