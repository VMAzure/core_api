﻿from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session
from fastapi_jwt_auth import AuthJWT
from app.database import SessionLocal
from app.models import Services, PurchasedServices, User, CreditTransaction
from pydantic import BaseModel
from sqlalchemy.sql import func
from datetime import datetime
from app.auth_helpers import get_admin_id, get_dealer_id, is_admin_user, is_dealer_user


import traceback
import sys
import logging
import os
from dotenv import load_dotenv
import uuid




# ✅ Carichiamo dotenv SOLO se non siamo in produzione
if os.getenv("ENV") != "production":
    load_dotenv()

# ✅ Configuriamo il logging
logging.basicConfig(level=logging.DEBUG, handlers=[logging.StreamHandler(sys.stdout)])
logger = logging.getLogger(__name__)
logger.debug("✅ DEBUG: Il logger è attivo e sta funzionando!")

# ✅ Inizializziamo Supabase con gestione migliorata degli errori
try:
    from supabase import create_client, Client

    SUPABASE_URL = os.getenv("SUPABASE_URL")
    SUPABASE_KEY = os.getenv("SUPABASE_KEY")

    # ✅ Debug per verificare il caricamento delle variabili
    if SUPABASE_URL is None or SUPABASE_KEY is None:
        raise ValueError("❌ ERRORE: Le credenziali Supabase non sono state caricate correttamente!")

    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

except ImportError as e:
    raise ImportError("❌ ERRORE: Supabase SDK non trovato! Installa con `pip install supabase`") from e

marketplace_router = APIRouter(prefix="/marketplace", tags=["Marketplace"])

# ✅ Funzione per ottenere la sessione DB
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
    admin_email: str = None
    service_id: int

@marketplace_router.post("/services")
async def add_service(
    name: str = Form(...),
    description: str = Form(...),
    price: float = Form(...),
    file: UploadFile = File(...),
     page_url: str = Form(...), 
    open_in_new_tab: bool = Form(True),  # ✅ Campo aggiunto
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    """
    Aggiunge un nuovo servizio con immagine caricata su Supabase Storage.
    """

    Authorize.jwt_required()
    user_id = Authorize.get_jwt_subject()

    user = db.query(User).filter(User.email == user_id).first()
    if not user or user.role != 'superadmin':
        raise HTTPException(status_code=403, detail="Accesso negato")

    allowed_extensions = {"png", "jpg", "jpeg", "webp"}
    file_extension = file.filename.split(".")[-1].lower()
    if file_extension not in allowed_extensions:
        raise HTTPException(status_code=400, detail="Formato file non valido!")

    file_content = await file.read()
    if len(file_content) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File troppo grande! Dimensione massima: 5MB.")

    try:
        file_name = f"services/{uuid.uuid4()}_{file.filename}"
        response = supabase.storage.from_("services").upload(
            file_name, file_content, {"content-type": file.content_type}
        )
        image_url = f"{SUPABASE_URL}/storage/v1/object/public/services/{file_name}"

    except Exception as e:
        logger.error(f"❌ ERRORE: Impossibile caricare l'immagine su Supabase: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    try:
        new_service = Services(
            name=name,
            description=description,
            price=price,
            image_url=image_url,
             page_url=page_url,
            open_in_new_tab=open_in_new_tab  # ✅ Salviamo nel DB
        )
        db.add(new_service)
        db.commit()
        db.refresh(new_service)

    except Exception as e:
        db.rollback()
        logger.error(f"❌ ERRORE: Impossibile salvare il servizio nel database: {e}")
        raise HTTPException(status_code=500, detail="Errore nel salvataggio del servizio.")

    return {
        "message": "Servizio aggiunto con successo",
        "service_id": new_service.id,
        "image_url": image_url
    }


@marketplace_router.get("/service-list", response_model=list)
def get_filtered_services(Authorize: AuthJWT = Depends(), db: Session = Depends(get_db)):
    """
    Recupera la lista dei servizi disponibili:
    - Se Super Admin, mostra tutti i servizi disponibili sempre attivi.
    - Se Admin, mostra tutti i servizi con il loro stato reale (acquistato o no).
    - Se Dealer, mostra solo i servizi acquistati dal proprio admin.
    """

    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()

    user = db.query(User).filter(User.email == user_email).first()
    if not user:
        raise HTTPException(status_code=404, detail="Utente non trovato")

    services = db.query(Services).all()

    if user.role == "superadmin":
        result = [{
            "id": service.id,
            "name": service.name,
            "description": service.description,
            "price": service.price,
            "image_url": service.image_url,
            "page_url": service.page_url,
            "open_in_new_tab": service.open_in_new_tab, 
            "is_active": True
        } for service in services]

    elif is_admin_user(user):
        admin_id = get_admin_id(user)

        purchased_services = {
            p.service_id for p in db.query(PurchasedServices).filter(
                PurchasedServices.admin_id == admin_id,
                PurchasedServices.status == 'active'
            ).all()
        }

        result = [{
            "id": service.id,
            "name": service.name,
            "description": service.description,
            "price": service.price,
            "image_url": service.image_url,
            "page_url": service.page_url if service.page_url else "#",
            "open_in_new_tab": service.open_in_new_tab, 
            "is_active": service.id in purchased_services
        } for service in services]

    elif user.role in ["dealer", "dealer_team"]:
        

        admin_id = get_admin_id(user)

        purchased_services = db.query(Services).join(PurchasedServices).filter(
            PurchasedServices.admin_id == admin_id,
            PurchasedServices.status == 'active'
        ).all()

        result = [{
            "id": service.id,
            "name": service.name,
            "description": service.description,
            "price": service.price,
            "image_url": service.image_url,
            "page_url": service.page_url if service.page_url else "#",
            "open_in_new_tab": service.open_in_new_tab, 
            "is_active": True
        } for service in purchased_services]

    else:
        raise HTTPException(status_code=403, detail="Ruolo non valido")

    return result


class PurchaseServiceRequest(BaseModel):
    service_id: int

@marketplace_router.post("/purchase-service")
async def purchase_service(
    request: PurchaseServiceRequest,
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    """
    Permette a un Admin o admin_team di acquistare o riattivare un servizio,
    verificando il credito disponibile dell'admin principale.
    """
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()

    user = db.query(User).filter(User.email == user_email).first()
    if not user or not is_admin_user(user):
        raise HTTPException(status_code=403, detail="Accesso negato: solo gli Admin possono acquistare servizi.")

    admin_id = get_admin_id(user)
    admin = db.query(User).filter(User.id == admin_id, User.role == "admin").first()
    if not admin:
        raise HTTPException(status_code=403, detail="Admin principale non trovato")

    # Recuperiamo il servizio richiesto
    service = db.query(Services).filter(Services.id == request.service_id).first()
    if not service:
        raise HTTPException(status_code=404, detail="Servizio non trovato.")

    # Controlla se è già stato acquistato
    existing_purchase = db.query(PurchasedServices).filter(
        PurchasedServices.admin_id == admin.id,
        PurchasedServices.service_id == request.service_id
    ).first()

    if existing_purchase:
        if existing_purchase.status == "sospeso":
            if admin.credit < service.price:
                raise HTTPException(status_code=402, detail="Credito insufficiente per riattivare il servizio.")

            admin.credit -= service.price
            existing_purchase.status = "active"
            existing_purchase.activated_at = datetime.utcnow()

            transaction = CreditTransaction(
                admin_id=admin.id,
                amount=service.price,
                transaction_type="USE"
            )

            db.add(transaction)
            db.commit()

            return {
                "message": "Servizio riattivato con successo!",
                "service_id": service.id,
                "remaining_credit": admin.credit
            }

        else:
            raise HTTPException(status_code=400, detail="Hai già acquistato questo servizio.")

    # Nuovo acquisto
    if admin.credit < service.price:
        raise HTTPException(status_code=402, detail="Credito insufficiente per acquistare il servizio.")

    try:
        admin.credit -= service.price

        transaction = CreditTransaction(
            admin_id=admin.id,
            amount=service.price,
            transaction_type="USE"
        )

        new_purchase = PurchasedServices(
            admin_id=admin.id,
            service_id=service.id,
            status="active",
            activated_at=datetime.utcnow()
        )

        db.add(transaction)
        db.add(new_purchase)
        db.commit()

        return {
            "message": "Servizio acquistato con successo!",
            "service_id": service.id,
            "remaining_credit": admin.credit
        }

    except Exception as e:
        db.rollback()
        logger.error(f"❌ ERRORE durante l'acquisto del servizio: {e}")
        raise HTTPException(status_code=500, detail="Errore nell'elaborazione dell'acquisto.")
