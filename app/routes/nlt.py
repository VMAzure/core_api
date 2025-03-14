from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import NltService, NltDocumentiRichiesti, NltPreventivi, Cliente, User
from pydantic import BaseModel
from jose import jwt, JWTError  # ✅ Aggiunto import corretto per decodificare il token JWT
from fastapi_jwt_auth import AuthJWT

import uuid
import httpx

import os

class Settings:
    authjwt_secret_key: str = "supersecretkey"

router = APIRouter(
    prefix="/nlt",
    tags=["nlt"]
)

AuthJWT.load_config
def get_config():
    return Settings()

def get_current_user(Authorize: AuthJWT = Depends(), db: Session = Depends(get_db)):
    try:
        Authorize.jwt_required()  # Verifica che il token sia presente
        user_id = Authorize.get_jwt_subject()  # Ottiene l'ID utente dal token

        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=401, detail="Utente non trovato")

        return user

    except Exception as e:
        raise HTTPException(status_code=401, detail="Token non valido o scaduto")


@router.get("/services")
async def get_nlt_services(db: Session = Depends(get_db)):
    services = db.query(NltService).filter(NltService.is_active == True).all()
    return {"services": services}

@router.get("/documenti-richiesti/{tipo_cliente}")
async def get_documenti_richiesti(tipo_cliente: str, db: Session = Depends(get_db)):
    documenti = db.query(NltDocumentiRichiesti)\
                  .filter(NltDocumentiRichiesti.tipo_cliente == tipo_cliente)\
                  .all()
    
    return {
        "tipo_cliente": tipo_cliente,
        "documenti": [doc.documento for doc in documenti]
    }

# 🔵 CONFIGURAZIONE SUPABASE
SUPABASE_URL = "https://vqfloobaovtdtcuflqeu.supabase.co"
SUPABASE_BUCKET = "nlt-preventivi"
SUPABASE_API_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InZxZmxvb2Jhb3Z0ZHRjdWZscWV1Iiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTczOTUzOTUzMCwiZXhwIjoyMDU1MTE1NTMwfQ.Lq-uIgXYZiBJK4ChfF_D7i5qYBDuxMfL2jY5GGKDuVk"

@router.post("/salva-preventivo")
async def salva_preventivo(
    file: UploadFile = File(...),
    cliente_id: int = Form(...),
    creato_da: int = Form(...),  # 👈 creato_da sempre presente
    marca: str = Form(...),
    modello: str = Form(...),
    durata: int = Form(...),
    km_totali: int = Form(...),
    anticipo: float = Form(...),
    canone: float = Form(...),
    db: Session = Depends(get_db)
):
    # 🔵 Genera un nome univoco per il file
    file_extension = file.filename.split(".")[-1]
    file_name = f"NLT_Offer_{uuid.uuid4()}.{file_extension}"
    file_path = f"{SUPABASE_BUCKET}/{file_name}"

    # 🔵 Carica il file su Supabase
    async with httpx.AsyncClient() as client:
        headers = {
            "Content-Type": file.content_type,
            "Authorization": f"Bearer {SUPABASE_API_KEY}"
        }
        response = await client.put(
            f"{SUPABASE_URL}/storage/v1/object/{file_path}",
            headers=headers,
            content=await file.read()
        )

    if response.status_code != 200:
        return {"success": False, "error": "Errore durante l'upload su Supabase."}

    # 🔵 URL pubblico sempre valido (senza scadenza)
    file_url = f"{SUPABASE_URL}/storage/v1/object/public/{file_path}"

    # 🔵 Salva il record nel database
    nuovo_preventivo = NltPreventivi(
        cliente_id=cliente_id,
        file_url=file_url,
        creato_da=creato_da,
        marca=marca,
        modello=modello,
        durata=durata,
        km_totali=km_totali,
        anticipo=anticipo,
        canone=canone,
        visibile=1
    )
    db.add(nuovo_preventivo)
    db.commit()
    db.refresh(nuovo_preventivo)

    return {
        "success": True,
        "file_url": file_url,
        "preventivo_id": nuovo_preventivo.id,
        "dati": {
            "marca": nuovo_preventivo.marca,
            "modello": nuovo_preventivo.modello,
            "durata": nuovo_preventivo.durata,
            "km_totali": nuovo_preventivo.km_totali,
            "anticipo": nuovo_preventivo.anticipo,
            "canone": nuovo_preventivo.canone
        }
    }




@router.get("/preventivi/{cliente_id}")
async def get_preventivi_cliente(cliente_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    # 🔍 Recupera il cliente
    cliente = db.query(Cliente).filter(Cliente.id == cliente_id).first()
    if not cliente:
        return {"success": False, "error": "Cliente non trovato"}

    # 🔍 Determina il nome del cliente
    nome_cliente = cliente.ragione_sociale if cliente.ragione_sociale else f"{cliente.nome} {cliente.cognome}".strip()

    # 🔹 Dealer: vede solo i suoi preventivi
    if current_user.role == "dealer":
        preventivi = db.query(NltPreventivi).filter(
            (NltPreventivi.creato_da == current_user.id) & (NltPreventivi.cliente_id == cliente_id)
        ).all()
    
    # 🔹 Admin: vede i suoi e quelli dei suoi dealer
    elif current_user.role == "admin":
        dealer_ids = db.query(User.id).filter(User.parent_id == current_user.id).subquery()
        preventivi = db.query(NltPreventivi).filter(
            (NltPreventivi.creato_da == current_user.id) | 
            (NltPreventivi.creato_da.in_(dealer_ids)) & (NltPreventivi.cliente_id == cliente_id)
        ).all()
    
    # 🔹 Superadmin: vede tutto per quel cliente
    else:
        preventivi = db.query(NltPreventivi).filter(NltPreventivi.cliente_id == cliente_id).all()

    return {
        "success": True,
        "cliente": nome_cliente,
        "preventivi": [
            {
                "id": p.id,
                "file_url": p.file_url,
                "creato_da": p.creato_da,
                "created_at": p.created_at,
                "marca": p.marca,
                "modello": p.modello,
                "durata": p.durata,
                "km_totali": p.km_totali,
                "anticipo": p.anticipo,
                "canone": p.canone
            }
            for p in preventivi
        ]
    }

@router.get("/preventivi")
async def get_miei_preventivi(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    try:
        print(f"📌 Richiesta ricevuta da user_id={current_user.id}, ruolo={current_user.role}")

        # 🔹 Dealer: vede solo i propri preventivi
        if current_user.role == "dealer":
            preventivi = db.query(NltPreventivi).filter(
                NltPreventivi.creato_da == current_user.id,
                NltPreventivi.visibile == 1
            ).all()
        
        # 🔹 Admin: vede i propri preventivi + quelli dei dealer associati
        elif current_user.role == "admin":
            dealer_ids = db.query(User.id).filter(User.parent_id == current_user.id).subquery()
            preventivi = db.query(NltPreventivi).filter(
                ((NltPreventivi.creato_da == current_user.id) | 
                 (NltPreventivi.creato_da.in_(dealer_ids))),
                NltPreventivi.visibile == 1
            ).all()
        
        # 🔹 Superadmin: vede tutto
        else:
            preventivi = db.query(NltPreventivi).filter(NltPreventivi.visibile == 1).all()

        print(f"✅ {len(preventivi)} preventivi trovati per user_id={current_user.id}")

        return {
            "success": True,
            "preventivi": [
                {
                    "id": p.id,
                    "file_url": p.file_url,
                    "creato_da": p.creato_da,
                    "created_at": p.created_at,
                    "marca": p.marca,
                    "modello": p.modello,
                    "durata": p.durata,
                    "km_totali": p.km_totali,
                    "anticipo": p.anticipo,
                    "canone": p.canone
                }
                for p in preventivi
            ]
        }
    
    except Exception as e:
        print(f"❌ ERRORE in get_miei_preventivi: {str(e)}", flush=True)
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}



@router.put("/nascondi-preventivo/{preventivo_id}")
async def nascondi_preventivo(preventivo_id: str, db: Session = Depends(get_db)):
    # 🔍 Cerca il preventivo nel database
    preventivo = db.query(NltPreventivi).filter(NltPreventivi.id == preventivo_id).first()

    if not preventivo:
        return {"success": False, "error": "Preventivo non trovato"}

    # 🔄 Imposta visibile = 0
    preventivo.visibile = 0
    db.commit()

    return {"success": True, "message": "Preventivo nascosto correttamente"}
