﻿from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session
from fastapi_jwt_auth import AuthJWT
from app.database import SessionLocal
from app.models import Services, PurchasedServices, User, CreditTransaction
from pydantic import BaseModel
from sqlalchemy.sql import func
from datetime import datetime
import traceback
import sys
import logging
import os
from dotenv import load_dotenv



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

    # ✅ Controlliamo il tipo di file per evitare estensioni non valide
    # ✅ Controlliamo il tipo di file
    allowed_extensions = {"png", "jpg", "jpeg", "webp"}
    file_extension = file.filename.split(".")[-1].lower()
    if file_extension not in allowed_extensions:
        raise HTTPException(status_code=400, detail="Formato file non valido!")

    # ✅ Leggi UNA sola volta il contenuto del file
    file_content = await file.read()

    if len(file_content) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File troppo grande! Dimensione massima: 5MB.")

    # ✅ Caricamento su Supabase usando file_content
    import uuid  # assicurati che ci sia

    # ✅ Caricamento su Supabase usando file_content con nome univoco
    try:
        file_name = f"services/{uuid.uuid4()}_{file.filename}"

        response = supabase.storage.from_("services").upload(
            file_name, file_content, {"content-type": file.content_type}
        )

        # ✅ Controlla correttamente la risposta
        if not hasattr(response, 'Key') or not response.Key:
            raise HTTPException(
                status_code=500,
                detail=f"Errore Supabase durante l'upload: {response}"
            )

        image_url = f"{SUPABASE_URL}/storage/v1/object/public/{file_name}"

    except Exception as e:
        logger.error(f"❌ ERRORE: Impossibile caricare l'immagine su Supabase: {e}")
        raise HTTPException(status_code=500, detail=str(e))




    # ✅ Salvataggio del servizio nel database con gestione del rollback
    try:
        new_service = Services(name=name, description=description, price=price, image_url=image_url)
        db.add(new_service)
        db.commit()
        db.refresh(new_service)
    except Exception as e:
        db.rollback()  # ✅ Rollback in caso di errore
        logger.error(f"❌ ERRORE: Impossibile salvare il servizio nel database: {e}")
        raise HTTPException(status_code=500, detail="Errore nel salvataggio del servizio.")

    return {"message": "Servizio aggiunto con successo", "service_id": new_service.id, "image_url": image_url}



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
            "is_active": True
        } for service in services]

    elif user.role == "admin":
        purchased_services = {p.service_id for p in db.query(PurchasedServices).filter(
            PurchasedServices.admin_id == user.id,
            PurchasedServices.status == 'active'
        ).all()}

        result = [{
            "id": service.id,
            "name": service.name,
            "description": service.description,
            "price": service.price,
            "image_url": service.image_url,
            "page_url": service.page_url if service.page_url else "#",
            "is_active": service.id in purchased_services
        } for service in services]

    elif user.role == "dealer":
        purchased_services = db.query(Services).join(PurchasedServices).filter(
            PurchasedServices.admin_id == user.parent_id,
            PurchasedServices.status == 'active'
        ).all()

        result = [{
            "id": service.id,
            "name": service.name,
            "description": service.description,
            "price": service.price,
            "image_url": service.image_url,
            "page_url": service.page_url if service.page_url else "#",
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
    Permette a un Admin di acquistare o riattivare un servizio, verificando il credito disponibile.
    """

    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()

    # Recuperiamo l'utente (Admin)
    user = db.query(User).filter(User.email == user_email).first()
    if not user or user.role != "admin":
        raise HTTPException(status_code=403, detail="Accesso negato: solo gli Admin possono acquistare servizi.")

    # Recuperiamo il servizio richiesto
    service = db.query(Services).filter(Services.id == request.service_id).first()
    if not service:
        raise HTTPException(status_code=404, detail="Servizio non trovato.")

    existing_purchase = db.query(PurchasedServices).filter(
        PurchasedServices.admin_id == user.id,
        PurchasedServices.service_id == request.service_id
    ).first()

    if existing_purchase:
        if existing_purchase.status == "sospeso":
            # Se il servizio è sospeso, controlla credito e riattiva
            if user.credit < service.price:
                raise HTTPException(status_code=402, detail="Credito insufficiente per riattivare il servizio.")

            user.credit -= service.price
            existing_purchase.status = "active"
            existing_purchase.activated_at = datetime.utcnow()  # Riattivazione servizio

            transaction = CreditTransaction(
                admin_id=user.id,
                amount=service.price,
                transaction_type="USE"
            )

            db.add(transaction)
            db.commit()

            return {
                "message": "Servizio riattivato con successo!",
                "service_id": service.id,
                "remaining_credit": user.credit
            }
        else:
            raise HTTPException(status_code=400, detail="Hai già acquistato questo servizio.")

    # Se il servizio non è mai stato acquistato, procedi con nuovo acquisto
    if user.credit < service.price:
        raise HTTPException(status_code=402, detail="Credito insufficiente per acquistare il servizio.")

    try:
        user.credit -= service.price

        transaction = CreditTransaction(
            admin_id=user.id,
            amount=service.price,
            transaction_type="USE"
        )

        new_purchase = PurchasedServices(
            admin_id=user.id,
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
            "remaining_credit": user.credit
        }

    except Exception as e:
        db.rollback()
        logger.error(f"❌ ERRORE durante l'acquisto del servizio: {e}")
        raise HTTPException(status_code=500, detail="Errore nell'elaborazione dell'acquisto.")
