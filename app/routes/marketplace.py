from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session
from fastapi_jwt_auth import AuthJWT
from app.database import SessionLocal
from app.models import Services, PurchasedServices, User, CreditTransaction
from pydantic import BaseModel
from sqlalchemy.sql import func
from datetime import datetime, timedelta
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

class AssignServiceRequest(BaseModel):
    admin_email: str = None
    service_id: int

@marketplace_router.post("/services")
async def add_service(
    name: str = Form(...),
    description: str = Form(...),
    file: UploadFile = File(...),
    page_url: str = Form(...),
    open_in_new_tab: bool = Form(True),

    # Ricorrenti
    activation_fee: float = Form(0.0),
    monthly_price: float = Form(0.0),
    quarterly_price: float = Form(0.0),
    semiannual_price: float = Form(0.0),
    annual_price: float = Form(0.0),

    # PXU (⚠️ arriva sempre come stringa)
    is_pay_per_use: str = Form("false"),
    pay_per_use_price: float = Form(0.0),

    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    """
    Crea un nuovo servizio:
    - Ricorrente: include billing cycle + attivazione
    - PXU: solo pay_per_use_price
    """
    Authorize.jwt_required()
    user_id = Authorize.get_jwt_subject()
    user = db.query(User).filter(User.email == user_id).first()

    if not user or user.role != "admin":
        raise HTTPException(status_code=403, detail="Accesso negato: solo l'admin può creare servizi.")

    # Validazioni
    for k, v in {
        "activation_fee": activation_fee,
        "monthly_price": monthly_price,
        "quarterly_price": quarterly_price,
        "semiannual_price": semiannual_price,
        "annual_price": annual_price,
        "pay_per_use_price": pay_per_use_price
    }.items():
        if v < 0:
            raise HTTPException(status_code=422, detail=f"Il campo '{k}' non può essere negativo.")

    allowed_extensions = {"png", "jpg", "jpeg", "webp"}
    file_extension = file.filename.split(".")[-1].lower()
    if file_extension not in allowed_extensions:
        raise HTTPException(status_code=400, detail="Formato file non valido! (consentiti: png, jpg, jpeg, webp)")

    file_content = await file.read()
    if len(file_content) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File troppo grande! Max 5MB.")

    try:
        file_name = f"services/{uuid.uuid4()}_{file.filename}"
        supabase.storage.from_("services").upload(
            file_name, file_content, {"content-type": file.content_type}
        )
        image_url = f"{SUPABASE_URL}/storage/v1/object/public/services/{file_name}"
    except Exception as e:
        logger.error(f"Upload Supabase fallito: {e}")
        raise HTTPException(status_code=500, detail="Errore upload immagine su storage.")

    try:
        new_service = Services(
            name=name,
            description=description,
            image_url=image_url,
            page_url=page_url,
            open_in_new_tab=open_in_new_tab,
            activation_fee=activation_fee,
            monthly_price=monthly_price,
            quarterly_price=quarterly_price,
            semiannual_price=semiannual_price,
            annual_price=annual_price,
            is_pay_per_use=is_pay_per_use.lower() == "true",
            pay_per_use_price=pay_per_use_price,
            price=0  # legacy compat
        )
        db.add(new_service)
        db.commit()
        db.refresh(new_service)
    except Exception as e:
        db.rollback()
        logger.error(f"Errore salvataggio servizio: {e}")
        raise HTTPException(status_code=500, detail="Errore nel salvataggio del servizio.")

    return {
        "message": "Servizio aggiunto con successo",
        "service_id": new_service.id,
        "image_url": image_url,
        "activation_fee": new_service.activation_fee,
        "monthly_price": new_service.monthly_price,
        "quarterly_price": new_service.quarterly_price,
        "semiannual_price": new_service.semiannual_price,
        "annual_price": new_service.annual_price,
        "is_pay_per_use": new_service.is_pay_per_use,
        "pay_per_use_price": new_service.pay_per_use_price
    }


@marketplace_router.get("/service-list", response_model=list)
def get_filtered_services(Authorize: AuthJWT = Depends(), db: Session = Depends(get_db)):
    """
    Restituisce:
    - per l’admin: tutti i servizi attivi
    - per un dealer: solo i servizi creati dall’admin, con `is_active` true se acquistati
    - per il team dealer: solo quelli attivi per il proprio dealer
    """
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()

    user = db.query(User).filter(User.email == user_email).first()
    if not user:
        raise HTTPException(status_code=404, detail="Utente non trovato")

    role = user.role
    user_id = user.id

    # === ADMIN ===
    if role in ["admin", "admin_team"]:
        services = db.query(Services).all()
        return [{
            "id": s.id,
            "name": s.name,
            "description": s.description,
            "image_url": s.image_url,
            "page_url": s.page_url or "#",
            "open_in_new_tab": s.open_in_new_tab,
            "is_active": True,
            "activation_fee": s.activation_fee,
            "monthly_price": s.monthly_price,
            "quarterly_price": s.quarterly_price,
            "semiannual_price": s.semiannual_price,
            "annual_price": s.annual_price,
            "is_pay_per_use": s.is_pay_per_use,
            "pay_per_use_price": s.pay_per_use_price
        } for s in services]



    # === DEALER / DEALER_TEAM ===
    elif role in ["dealer", "dealer_team"]:
        dealer_id = get_dealer_id(user)

        # Servizi disponibili
        all_services = db.query(Services).all()

        # Servizi acquistati da questo dealer
        purchases = db.query(PurchasedServices).filter(
            PurchasedServices.dealer_id == dealer_id
        ).all()

        purchases_map = {p.service_id: p for p in purchases}

        result = []
        for s in all_services:
            purchased = purchases_map.get(s.id)
            result.append({
                "id": s.id,
                "name": s.name,
                "description": s.description,
                "image_url": s.image_url,
                "page_url": s.page_url or "#",
                "open_in_new_tab": s.open_in_new_tab,
                "is_active": purchased.status == "attivo" if purchased else False,
                "activation_fee": s.activation_fee,
                "monthly_price": s.monthly_price,
                "quarterly_price": s.quarterly_price,
                "semiannual_price": s.semiannual_price,
                "annual_price": s.annual_price,
                "is_pay_per_use": s.is_pay_per_use,
                "pay_per_use_price": s.pay_per_use_price,
                "purchased_service": {
                    "id": purchased.id,
                    "status": purchased.status,
                    "billing_cycle": purchased.billing_cycle,
                    "next_renewal_at": purchased.next_renewal_at.isoformat() if purchased.next_renewal_at else None
                } if purchased else None
            })

        return result


    else:
        raise HTTPException(status_code=403, detail="Ruolo non autorizzato")



# --- Richiesta ---
class PurchaseServiceRequest(BaseModel):
    service_id: int
    billing_cycle: str  # "monthly", "quarterly", "semiannual", "annual"

# --- Utility ---
def calcola_prossima_scadenza(start: datetime, ciclo: str) -> datetime:
    if ciclo == "monthly":
        return start + timedelta(days=30)
    elif ciclo == "quarterly":
        return start + timedelta(days=90)
    elif ciclo == "semiannual":
        return start + timedelta(days=182)
    elif ciclo == "annual":
        return start + timedelta(days=365)
    return start + timedelta(days=30)  # fallback

# --- Endpoint ---
@marketplace_router.post("/purchase-service")
async def purchase_service(
    request: PurchaseServiceRequest,
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()

    user = db.query(User).filter(User.email == user_email).first()
    if not user or not is_dealer_user(user):
        raise HTTPException(status_code=403, detail="Solo i dealer possono acquistare servizi.")

    dealer_id = get_dealer_id(user)
    dealer = db.query(User).filter(User.id == dealer_id, User.role == "dealer").first()
    if not dealer:
        raise HTTPException(status_code=404, detail="Dealer principale non trovato.")

    service = db.query(Services).filter(Services.id == request.service_id).first()
    if not service:
        raise HTTPException(status_code=404, detail="Servizio non trovato.")

    valid_cycles = ["monthly", "quarterly", "semiannual", "annual"]
    if request.billing_cycle not in valid_cycles:
        raise HTTPException(status_code=422, detail="Piano di fatturazione non valido.")

    billing_price = {
        "monthly": service.monthly_price,
        "quarterly": service.quarterly_price,
        "semiannual": service.semiannual_price,
        "annual": service.annual_price
    }.get(request.billing_cycle, 0)

    existing = db.query(PurchasedServices).filter(
        PurchasedServices.dealer_id == dealer.id,
        PurchasedServices.service_id == service.id
    ).first()

    total_cost = billing_price
    is_new_activation = False
    activated_at = datetime.utcnow()
    next_renewal = calcola_prossima_scadenza(activated_at, request.billing_cycle)

    if not existing:
        # Prima attivazione → aggiunge costo attivazione
        total_cost += service.activation_fee
        is_new_activation = True

        new_purchase = PurchasedServices(
            dealer_id=dealer.id,
            service_id=service.id,
            status="attivo",
            activated_at=activated_at,
            billing_cycle=request.billing_cycle,
            next_renewal_at=next_renewal
        )
        db.add(new_purchase)

    elif existing.status == "sospeso":
        # Riattivazione → non paga activation fee
        existing.status = "attivo"
        existing.activated_at = activated_at
        existing.billing_cycle = request.billing_cycle
        existing.next_renewal_at = next_renewal

    else:
        raise HTTPException(status_code=400, detail="Servizio già attivo per questo dealer.")

    if dealer.credit < total_cost:
        raise HTTPException(status_code=402, detail="Credito insufficiente")

    dealer.credit -= total_cost

    transaction = CreditTransaction(
        dealer_id=dealer.id,
        amount=total_cost,
        transaction_type="USE"
    )
    db.add(transaction)

    try:
        db.commit()
        return {
            "message": f"Servizio acquistato con successo ({'prima attivazione' if is_new_activation else 'riattivazione'})",
            "service_id": service.id,
            "billing_cycle": request.billing_cycle,
            "activation_fee_applied": is_new_activation,
            "total_cost": total_cost,
            "next_renewal_at": next_renewal.isoformat(),
            "remaining_credit": dealer.credit
        }

    except Exception as e:
        db.rollback()
        logger.error(f"❌ Errore acquisto servizio: {e}")
        raise HTTPException(status_code=500, detail="Errore durante l'acquisto del servizio.")


class UseServiceRequest(BaseModel):
    service_id: int


@marketplace_router.post("/use-service")
def use_pay_per_use_service(
    payload: UseServiceRequest,
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()

    user = db.query(User).filter(User.email == user_email).first()
    if not user or not is_dealer_user(user):
        raise HTTPException(status_code=403, detail="Accesso riservato ai dealer.")

    dealer_id = get_dealer_id(user)

    service = db.query(Services).filter(Services.id == payload.service_id).first()
    if not service:
        raise HTTPException(status_code=404, detail="Servizio non trovato.")

    if not service.is_pay_per_use:
        raise HTTPException(status_code=400, detail="Questo servizio non è pay-per-use.")

    costo = service.pay_per_use_price or 0.0
    if user.credit < costo:
        raise HTTPException(status_code=402, detail="Credito insufficiente.")

    # Scala il credito
    user.credit -= costo

    # Registra la transazione
    transazione = CreditTransaction(
        dealer_id=dealer_id,
        amount=costo,
        transaction_type="USE"
    )
    db.add(transazione)

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail="Errore nell'utilizzo del servizio.")

    # Risposta con page_url firmata
    token = Authorize.get_raw_jwt()
    token_str = Authorize.get_token()
    final_url = f"{service.page_url}?token={token_str}"

    return {
        "message": "Servizio usato correttamente",
        "page_url": final_url,
        "remaining_credit": user.credit
    }
