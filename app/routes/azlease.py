from fastapi import Depends, HTTPException, APIRouter
from sqlalchemy.orm import Session
from fastapi_jwt_auth import AuthJWT
from app.database import get_db
from app.models import User, AZUsatoInsertRequest
from app.schemas import AutoUsataCreate
import uuid
from datetime import datetime
from sqlalchemy import text

router = APIRouter()

@router.post("/usato", tags=["AZLease"])
async def inserisci_auto_usata(
    payload: AZUsatoInsertRequest,
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()
    user = db.query(User).filter(User.email == user_email).first()

    if not user:
        raise HTTPException(status_code=401, detail="Utente non trovato")

    if user.role not in ["dealer", "admin", "superadmin"]:
        raise HTTPException(status_code=403, detail="Ruolo non autorizzato")

    # 🔁 Determina admin_id e dealer_id in base al ruolo
    # Determina admin_id e dealer_id in base al ruolo
    dealer_id = None
    admin_id = None

    if user.role == "dealer":
        dealer_id = str(user.id)  # Assicurati che questo sia un UUID
        admin_id = str(user.parent_id)  # Qui user.parent_id dovrebbe essere un UUID, ma lo convertirò in str per coerenza
    else:  # admin o superadmin
        admin_id = str(user.id)

    # Aggiungi una conversione esplicita in UUID
    admin_id = uuid.UUID(admin_id)  # Converti admin_id in UUID, se necessario

    # 1️⃣ Inserisci in AZLease_UsatoIN
    usatoin_id = uuid.uuid4()
    db.execute(text("""
        INSERT INTO azlease_usatoin (
            id, dealer_id, admin_id, data_inserimento, data_ultima_modifica, prezzo_costo, prezzo_vendita
        )
        VALUES (
            :id, :dealer_id, :admin_id, :inserimento, :modifica, :costo, :vendita
        )
    """), {
        "id": str(usatoin_id),
        "dealer_id": dealer_id if dealer_id else None,  # Gestisci il None in modo esplicito
        "admin_id": admin_id,  # Ora admin_id è un UUID
        "inserimento": datetime.utcnow(),
        "modifica": datetime.utcnow(),
        "costo": payload.prezzo_costo,
        "vendita": payload.prezzo_vendita
    })
    # 2️⃣ Inserisci in AZLease_UsatoAuto
    auto_id = uuid.uuid4()
    db.execute(text("""
        INSERT INTO azlease_usatoauto (
            id, targa, anno_immatricolazione, data_passaggio_proprieta, km_certificati,
            data_ultimo_intervento, descrizione_ultimo_intervento, cronologia_tagliandi, doppie_chiavi,
            codice_motornet, colore, id_usatoin
        ) VALUES (
            :id, :targa, :anno, :passaggio, :km,
            :intervento_data, :intervento_desc, :tagliandi, :chiavi,
            :codice, :colore, :usatoin_id
        )
    """), {
        "id": str(auto_id),
        "targa": payload.targa,
        "anno": payload.anno_immatricolazione,
        "passaggio": payload.data_passaggio_proprieta,
        "km": payload.km_certificati,
        "intervento_data": payload.data_ultimo_intervento,
        "intervento_desc": payload.descrizione_ultimo_intervento,
        "tagliandi": payload.cronologia_tagliandi,
        "chiavi": payload.doppie_chiavi,
        "codice": payload.codice_motornet,
        "colore": payload.colore,
        "usatoin_id": str(usatoin_id)  # Assicurati che usatoin_id sia passato come stringa, se richiesto dal database
    })

    db.commit()

    return {
        "message": "Auto inserita correttamente",
        "id_auto": str(auto_id),
        "id_inserimento": str(usatoin_id)
    }
