from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from fastapi_jwt_auth import AuthJWT
from app.database import SessionLocal  # Importiamo solo SessionLocal
from app.models import Services, PurchasedServices, User
from pydantic import BaseModel
from sqlalchemy.sql import func

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
@marketplace_router.post("/assign-service")
def assign_service(
    request: AssignServiceRequest, 
    Authorize: AuthJWT = Depends(), 
    db: Session = Depends(get_db)
):
    try:
        Authorize.jwt_required()
        superadmin_email = Authorize.get_jwt_subject()

        # Verifica che chi effettua l'operazione sia un Super Admin
        superadmin = db.query(User).filter(User.email == superadmin_email).first()
        if not superadmin or superadmin.role != "superadmin":
            print("❌ DEBUG: Accesso negato - Utente non è un Super Admin")
            raise HTTPException(status_code=403, detail="Accesso negato")

        # Verifica che l'Admin esista
        admin = db.query(User).filter(User.email == request.admin_email, User.role == "admin").first()
        if not admin:
            print(f"❌ DEBUG: Admin {request.admin_email} non trovato")
            raise HTTPException(status_code=404, detail="Admin non trovato")

        # Verifica che il servizio esista
        service = db.query(Services).filter(Services.id == request.service_id).first()
        if not service:
            print(f"❌ DEBUG: Servizio con ID {request.service_id} non trovato")
            raise HTTPException(status_code=404, detail="Servizio non trovato")

        # Controlla il credito disponibile usando la nuova tabella
        total_credit = db.query(func.sum(CreditTransaction.amount)).filter(
            CreditTransaction.admin_id == admin.id
        ).scalar() or 0  # Se non ci sono transazioni, credito iniziale è 0

        print(f"🔍 DEBUG: Credito totale disponibile: {total_credit}, Prezzo Servizio: {service.price}")

        if total_credit < service.price:
            raise HTTPException(status_code=400, detail="Credito insufficiente per attivare il servizio")

        # Registra la transazione di utilizzo credito
        new_transaction = CreditTransaction(
            admin_id=admin.id, amount=-service.price, transaction_type="USE"
        )
        db.add(new_transaction)
        db.commit()

        return {"message": f"Servizio assegnato con successo a {admin.email}, Credito rimanente: {total_credit - service.price}"}

    except Exception as e:
        db.rollback()
        print(f"❌ ERRORE GENERICO: {str(e)}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Errore interno: {str(e)}")

@marketplace_router.post("/buy-service")
def buy_service(
    request: AssignServiceRequest, 
    Authorize: AuthJWT = Depends(), 
    db: Session = Depends(get_db)
):
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
        raise HTTPException(status_code=400, detail="Hai già acquistato questo servizio")

    # Controlla se l'Admin ha credito sufficiente
    if admin.credit < service.price:
        print(f"❌ DEBUG: Credito insufficiente per Admin {admin.email}")
        raise HTTPException(status_code=400, detail="Credito insufficiente per attivare il servizio")

    # Scalare il credito e assegnare il servizio
    # Scalare il credito e assegnare il servizio
    print(f"✅ DEBUG: Scalando {service.price} crediti da {admin.email}, Credito prima: {admin.credit}")
    admin.credit -= service.price
    db.add(new_purchase)
    db.commit()
    print(f"✅ DEBUG: Credito aggiornato per {admin.email}, Nuovo saldo: {admin.credit}")
    db.refresh(new_purchase)
    db.refresh(admin)

    return {
        "message": f"Servizio acquistato con successo",
        "admin_credito_rimanente": admin.credit
    }

