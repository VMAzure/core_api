from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session
from fastapi_jwt_auth import AuthJWT
from app.database import SessionLocal
from app.models import Services, PurchasedServices, User, CreditTransaction
from pydantic import BaseModel
from sqlalchemy.sql import func
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
    allowed_extensions = {"png", "jpg", "jpeg", "webp"}
    file_extension = file.filename.split(".")[-1].lower()
    if file_extension not in allowed_extensions:
        raise HTTPException(status_code=400, detail="Formato file non valido! Usa PNG, JPG, JPEG, WEBP.")

    # ✅ Controlliamo la dimensione del file (max 5MB)
    file_size = await file.read()
    if len(file_size) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File troppo grande! Dimensione massima: 5MB.")

    # ✅ Resettiamo il puntatore del file per poterlo riutilizzare
    file.file.seek(0)

    # ✅ Caricamento dell'immagine su Supabase
    try:
        file_name = f"services/{file.filename}"
        file_content = await file.read()  # ✅ Convertiamo il file in `bytes`
        
        response = supabase.storage.from_("services").upload(file_name, file_content, {"content-type": file.content_type})

        # ✅ Estrarre il contenuto della risposta
        response_data = response.json()  # Convertiamo la risposta in JSON

        if response.status_code != 200:
            raise HTTPException(status_code=500, detail=f"Errore nel caricamento dell'immagine: {response_data}")

        image_url = f"{SUPABASE_URL}/storage/v1/object/public/services/services/{file.filename}"

    except Exception as e:
        logger.error(f"❌ ERRORE: Impossibile caricare l'immagine su Supabase: {e}")
        raise HTTPException(status_code=500, detail=f"Errore nel caricamento dell'immagine: {str(e)}")

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
    Recupera la lista dei servizi disponibili e verifica quali sono attivi per l'Admin.
    """

    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()

    user = db.query(User).filter(User.email == user_email).first()
    if not user:
        raise HTTPException(status_code=403, detail="Accesso negato")

    # 🔹 Recuperiamo tutti i servizi con la `page_url` associata
    services = db.query(Services, ServicePages.page_url).outerjoin(ServicePages, Services.id == ServicePages.service_id).all()

    # 🔹 Recuperiamo i servizi acquistati dall'Admin
    purchased_services = {p.service_id for p in db.query(PurchasedServices).filter(PurchasedServices.admin_id == user.id).all()}

    return [{
        "id": service.id,
        "name": service.name,
        "description": service.description,
        "price": service.price,
        "image_url": service.image_url,
        "is_active": service.id in purchased_services,  # 🔹 Indichiamo se il servizio è attivo
        "page_url": page_url if page_url else "#"  # ✅ Aggiungiamo il link della pagina
    } for service, page_url in services]



class PurchaseServiceRequest(BaseModel):
    service_id: int

@marketplace_router.post("/purchase-service")
async def purchase_service(
    request: PurchaseServiceRequest,  # ✅ Ora FastAPI leggerà "service_id" dal JSON
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    """
    Permette a un Admin di acquistare un servizio, verificando il credito disponibile.
    """

    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()

    # ✅ Recuperiamo l'utente (Admin)
    user = db.query(User).filter(User.email == user_email).first()
    if not user or user.role != "admin":
        raise HTTPException(status_code=403, detail="Accesso negato: solo gli Admin possono acquistare servizi.")

    # ✅ Recuperiamo il servizio richiesto
    service = db.query(Services).filter(Services.id == request.service_id).first()
    if not service:
        raise HTTPException(status_code=404, detail="Servizio non trovato.")

    # ✅ Controlliamo se il servizio è già attivo per l'Admin
    existing_purchase = db.query(PurchasedServices).filter(
        PurchasedServices.admin_id == user.id,
        PurchasedServices.service_id == service.id
    ).first()

    if existing_purchase:
        raise HTTPException(status_code=400, detail="Hai già acquistato questo servizio.")

    # ✅ Controlliamo il credito dell'Admin
    if user.credit < service.price:
        raise HTTPException(status_code=402, detail="Credito insufficiente per acquistare il servizio.")

    try:
        # 🔹 Sottraiamo il costo dal credito dell'Admin
        user.credit -= service.price
        db.commit()

        # 🔹 Registriamo la transazione nei log di credito
        transaction = CreditTransaction(
        admin_id=user.id,
        amount=service.price,  # ✅ Inseriamo il valore positivo
        transaction_type="USE"  # ✅ Cambiamo "Acquisto servizio" con "USE"
)

        db.add(transaction)
        db.commit()

        # 🔹 Salviamo l'attivazione del servizio
        new_purchase = PurchasedServices(admin_id=user.id, service_id=service.id, status="active")
        db.add(new_purchase)
        db.commit()

        return {"message": "Servizio acquistato con successo!", "service_id": service.id, "remaining_credit": user.credit}

    except Exception as e:
        db.rollback()
        logger.error(f"❌ ERRORE durante l'acquisto del servizio: {e}")
        raise HTTPException(status_code=500, detail="Errore nell'elaborazione dell'acquisto.")