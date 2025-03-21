
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from fastapi_jwt_auth import AuthJWT
from app.database import get_db
from app.models import User, AZLease_UsatoIN, AZLease_UsatoAuto
from app.models import AutoUsataInput  # importa lo schema definito sopra

router = APIRouter()


@router.post("/usato", tags=["AZLease"])
async def inserisci_auto_usata(
    payload: AutoUsataInput,
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()

    user = db.query(User).filter(User.email == user_email).first()

    if not user or user.role != "dealer":
        raise HTTPException(status_code=403, detail="Accesso riservato ai dealer")

    # Inserimento in tabella AZLease_UsatoIN
    nuovo_inserimento = AZLease_UsatoIN(
        dealer_id=user.id,
        admin_id=user.parent_id,  # legame con admin
        prezzo_costo=payload.prezzo_costo,
        prezzo_vendita=payload.prezzo_vendita
    )
    db.add(nuovo_inserimento)
    db.commit()
    db.refresh(nuovo_inserimento)

    # Inserimento in tabella AZLease_UsatoAuto
    nuova_auto = AZLease_UsatoAuto(
        targa=payload.targa,
        anno_immatricolazione=payload.anno_immatricolazione,
        data_passaggio_proprieta=payload.data_passaggio_proprieta,
        km_certificati=payload.km_certificati,
        data_ultimo_intervento=payload.data_ultimo_intervento,
        descrizione_ultimo_intervento=payload.descrizione_ultimo_intervento,
        cronologia_tagliandi=payload.cronologia_tagliandi,
        doppie_chiavi=payload.doppie_chiavi,
        codice_motornet=payload.codice_motornet,
        colore=payload.colore,
        id_usatoin=nuovo_inserimento.id
    )
    db.add(nuova_auto)
    db.commit()
    db.refresh(nuova_auto)

    return {
        "message": "Auto usata inserita correttamente",
        "inserimento_id": nuovo_inserimento.id,
        "auto_id": nuova_auto.id
    }

