from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session
from fastapi_jwt_auth import AuthJWT
from app.database import SessionLocal  # Manteniamo la gestione DB centralizzata
from app.models import Services, PurchasedServices, User, CreditTransaction  # Importiamo solo i modelli necessari
from pydantic import BaseModel
from sqlalchemy.sql import func
import traceback
import sys
import logging
import os
from dotenv import load_dotenv

# ✅ Carichiamo variabili d'ambiente come in database.py
load_dotenv()

print("✅ DEBUG - SUPABASE_URL:", os.getenv("SUPABASE_URL"))
print("✅ DEBUG - SUPABASE_KEY:", os.getenv("SUPABASE_KEY"))


# ✅ Configuriamo il logging per il debug
logging.basicConfig(level=logging.DEBUG, handlers=[logging.StreamHandler(sys.stdout)])
logger = logging.getLogger(__name__)
logger.debug("✅ DEBUG: Il logger è attivo e sta funzionando!")

# ✅ Inizializziamo Supabase
try:
    from supabase import create_client, Client

    SUPABASE_URL = os.getenv("SUPABASE_URL")
    SUPABASE_KEY = os.getenv("SUPABASE_KEY")

    if not SUPABASE_URL or not SUPABASE_KEY:
        raise ValueError("❌ ERRORE: Le credenziali Supabase non sono state caricate correttamente!")

    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

except ImportError as e:
    raise ImportError("❌ ERRORE: Supabase SDK non trovato! Installa con `pip install supabase`") from e

marketplace_router = APIRouter(prefix="/marketplace", tags=["Marketplace"])

# ✅ Funzione per ottenere la sessione DB (allineata con database.py)
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
    admin_email: str = None  # Facoltativo, usato solo se il Super Admin assegna un servizio
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
    Authorize.jwt_required()
    user_id = Authorize.get_jwt_subject()

    user = db.query(User).filter(User.email == user_id).first()
    if not user or user.role != 'superadmin':
        raise HTTPException(status_code=403, detail="Accesso negato")

    # ✅ Caricamento dell'immagine su Supabase Storage con gestione degli errori migliorata
    try:
        file_content = await file.read()
        file_name = f"services/{file.filename}"

        if not supabase:
            raise HTTPException(status_code=500, detail="Supabase non è stato inizializzato correttamente")

        response = supabase.storage.from_("services").upload(file_name, file_content, {"content-type": file.content_type})

        if "error" in response:
            raise HTTPException(status_code=500, detail="Errore nel caricamento dell'immagine su Supabase")

        image_url = f"{SUPABASE_URL}/storage/v1/object/public/services/{file_name}"

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Errore nel caricamento dell'immagine: {str(e)}")

    # ✅ Salvataggio del servizio nel database
    new_service = Services(name=name, description=description, price=price, image_url=image_url)
    db.add(new_service)
    db.commit()
    db.refresh(new_service)

    return {"message": "Servizio aggiunto con successo", "service_id": new_service.id, "image_url": image_url}

@marketplace_router.get("/service-list", response_model=list)
def get_filtered_services(Authorize: AuthJWT = Depends(), db: Session = Depends(get_db)):
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()

    user = db.query(User).filter(User.email == user_email).first()
    if not user:
        raise HTTPException(status_code=403, detail="Accesso negato")

    services = db.query(Services).all()

    return [{
        "id": service.id,
        "name": service.name,
        "description": service.description,
        "price": service.price,
        "image_url": service.image_url  # ✅ Ora includiamo correttamente l'immagine nella risposta
    } for service in services]

