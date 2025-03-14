﻿from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException, Security, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import NltService, NltDocumentiRichiesti, NltPreventivi, Cliente, User
from pydantic import BaseModel, BaseSettings
from jose import jwt, JWTError  # ✅ Aggiunto import corretto per decodificare il token JWT
from fastapi_jwt_auth import AuthJWT
from typing import Optional

import uuid
import httpx
import os


class Settings(BaseSettings):
    authjwt_secret_key: str = os.getenv("SECRET_KEY", "supersecretkey")  # ✅ Ora usa Pydantic

@AuthJWT.load_config
def get_config():
    return Settings()


router = APIRouter(
    prefix="/nlt",
    tags=["nlt"]
)

def get_current_user(Authorize: AuthJWT = Depends(), db: Session = Depends(get_db)):
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()

    user = db.query(User).filter(User.email == user_email).first()
    if not user:
        raise HTTPException(status_code=401, detail="Utente non trovato")
    return user



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
async def get_preventivi_cliente(
    cliente_id: int, 
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):

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
async def get_miei_preventivi(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
    search: Optional[str] = Query(None)
):
    offset = (page - 1) * size

    if current_user.role == "dealer":
        query = db.query(NltPreventivi).join(Cliente).filter(
            NltPreventivi.creato_da == current_user.id,
            NltPreventivi.visibile == 1
        )
    elif current_user.role == "admin":
        dealer_ids = db.query(User.id).filter(User.parent_id == current_user.id).subquery()
        query = db.query(NltPreventivi).join(Cliente).filter(
            ((NltPreventivi.creato_da == current_user.id) |
             (NltPreventivi.creato_da.in_(dealer_ids))),
            NltPreventivi.visibile == 1
        )
    else:  # superadmin
        query = db.query(NltPreventivi).join(Cliente).filter(NltPreventivi.visibile == 1)

    # 🔍 Aggiungi filtro ricerca
    if search:
        search_term = f"%{search}%"
        query = query.filter(
            (Cliente.nome.ilike(search_term)) |
            (Cliente.cognome.ilike(search_term)) |
            (Cliente.ragione_sociale.ilike(search_term))
        )

    offset = (page - 1) * size

    preventivi = query.order_by(NltPreventivi.created_at.desc()) \
                      .offset(offset) \
                      .limit(size) \
                      .all()

    risultati = []
    for p in preventivi:
        cliente = p.cliente
        
        if cliente.tipo_cliente == "Società":
            nome_cliente = cliente.ragione_sociale or "NN"
        else:
            nome_cliente = f"{cliente.nome or ''} {cliente.cognome or ''}".strip() or "NN"

        risultati.append({
            "id": p.id,
            "file_url": p.file_url,
            "creato_da": p.creato_da,
            "created_at": p.created_at,
            "marca": p.marca,
            "modello": p.modello,
            "durata": p.durata,
            "km_totali": p.km_totali,
            "anticipo": p.anticipo,
            "canone": p.canone,
            "cliente": nome_cliente
        })

    return {
        "success": True,
            "preventivi": risultati,
            "page": page,
            "size": size,
            "count": len(risultati)
    }




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
