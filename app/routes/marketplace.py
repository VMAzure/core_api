from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from fastapi_jwt_auth import AuthJWT
from app.database import SessionLocal  # Importiamo solo SessionLocal
from app.models import Services, PurchasedServices, User, CreditTransaction  # Importiamo solo i modelli necessari
from pydantic import BaseModel
from sqlalchemy.sql import func
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

        # Controllo credito dall'Admin (uso direttamente admin.credit)
        total_credit = admin.credit

        print(f"🔍 DEBUG: Credito Admin {admin.email}: {total_credit}, Prezzo Servizio: {service.price}")
        sys.stdout.flush()

        if total_credit < service.price:
            print("❌ DEBUG: Credito insufficiente!")
            raise HTTPException(status_code=400, detail="Credito insufficiente per attivare il servizio")

        # Scalare il credito e registrare la transazione
        admin.credit -= service.price
        new_transaction = CreditTransaction(
            admin_id=admin.id, amount=-service.price, transaction_type="USE"
        )
        db.add(new_transaction)
        db.commit()
        db.refresh(admin)

        print(f"✅ DEBUG: Servizio assegnato, nuovo credito: {admin.credit}")
        sys.stdout.flush()

        return {"message": f"Servizio assegnato con successo a {admin.email}, Credito rimanente: {admin.credit}"}

    except Exception as e:
        db.rollback()
        print(f"❌ ERRORE GENERICO: {str(e)}")
        traceback.print_exc()
        sys.stdout.flush()
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
            raise HTTPException(status_code=400, detail="Hai già acquistato questo servizio")

        # Controllo del credito dell'Admin
        total_credit = admin.credit

        print(f"🔍 DEBUG: Credito Admin {admin.email}: {total_credit}, Prezzo Servizio: {service.price}")
        sys.stdout.flush()

        if total_credit < service.price:
            print("❌ DEBUG: Credito insufficiente per Admin!")
            raise HTTPException(status_code=400, detail="Credito insufficiente per attivare il servizio")

        # Scalare il credito e registrare l'acquisto
        admin.credit -= service.price
        new_purchase = PurchasedServices(admin_id=admin.id, service_id=service.id)
        db.add(new_purchase)
        db.commit()
        db.refresh(admin)

        print(f"✅ DEBUG: Servizio acquistato, nuovo credito: {admin.credit}")
        sys.stdout.flush()

        return {
            "message": f"Servizio acquistato con successo",
            "admin_credito_rimanente": admin.credit
        }

    except Exception as e:
        db.rollback()
        print(f"❌ ERRORE GENERICO: {str(e)}")
        traceback.print_exc()
        sys.stdout.flush()
        raise HTTPException(status_code=500, detail=f"Errore interno: {str(e)}")

@marketplace_router.put("/update-duration")
def update_service_duration(duration: int, Authorize: AuthJWT = Depends(), db: Session = Depends(get_db)):
    """Permette al Super Admin di modificare la durata dei servizi"""
    Authorize.jwt_required()
    user_id = Authorize.get_jwt_subject()

    # Debug: Log dell'utente
    print(f"🔍 DEBUG: Richiesta da {user_id}, durata richiesta: {duration}")

    user = db.query(User).filter(User.email == user_id).first()
    if not user or user.role != "superadmin":
        print("❌ DEBUG: Accesso negato - Utente non è Super Admin")
        raise HTTPException(status_code=403, detail="Accesso negato")

    # Controlliamo se esiste già un record nella tabella settings
    setting = db.execute(text("SELECT * FROM settings")).fetchone()
    print(f"🔍 DEBUG: Setting attuale: {setting}")

    try:
        if setting:
            db.execute("UPDATE settings SET service_duration_minutes = :duration", {"duration": duration})
        else:
            db.execute("INSERT INTO settings (service_duration_minutes) VALUES (:duration)", {"duration": duration})

        db.commit()
        print(f"✅ DEBUG: Durata aggiornata con successo a {duration} minuti")

        return {"message": f"Durata servizio aggiornata a {duration} minuti"}

    except Exception as e:
        db.rollback()
        print(f"❌ ERRORE: {str(e)}")
        raise HTTPException(status_code=500, detail="Errore nell'aggiornamento della durata")

