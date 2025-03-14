from fastapi import APIRouter, Depends, UploadFile, File, Form
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import NltService, NltDocumentiRichiesti, NltPreventivi, Cliente
from pydantic import BaseModel
import uuid
import httpx

router = APIRouter(
    prefix="/nlt",
    tags=["nlt"]
)

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
        canone=canone
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
async def get_preventivi_cliente(cliente_id: int, db: Session = Depends(get_db)):
    # Recupera il cliente
    cliente = db.query(Cliente).filter(Cliente.id == cliente_id).first()
    if not cliente:
        return {"success": False, "error": "Cliente non trovato"}

    # Determina il nome del cliente (Ragione Sociale o Nome + Cognome)
    nome_cliente = cliente.ragione_sociale if cliente.ragione_sociale else f"{cliente.nome} {cliente.cognome}".strip()

    # Recupera tutti i preventivi associati al cliente
    preventivi = db.query(NltPreventivi).filter(NltPreventivi.cliente_id == cliente_id).all()

    # Se non ci sono preventivi, restituisce un array vuoto
    if not preventivi:
        return {"success": True, "cliente": nome_cliente, "preventivi": []}

    # Formatta i risultati in un array di dizionari, includendo i nuovi campi
    lista_preventivi = [
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

    return {
        "success": True,
        "cliente": nome_cliente,  # 👈 Ora restituisce il nome o la ragione sociale
        "preventivi": lista_preventivi
    }
