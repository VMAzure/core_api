from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime
from app.database import get_db
from app.routes.azinsurance.models_azinsurance import (
    AssPreventivo, AssPolizza, AssIncasso,
    AssPreventivoGaranzia, AssPreventivoRischio, AssPreventivoConferma, AssPreventivoGaranziaMF
)
from app.routes.azinsurance.schemas_azinsurance import (
    PreventivoCreate, ConfermaPreventivo, PolizzaCreate, IncassoCreate,
    PreventivoResponse, PolizzaResponse, IncassoResponse
)
import uuid
from typing import List
from fastapi_jwt_auth import AuthJWT


# Verifica JWT e Ruolo
def check_admin_or_admin_team(Authorize: AuthJWT = Depends()):
    Authorize.jwt_required()
    user_claims = Authorize.get_raw_jwt()
    user_role = user_claims.get('role')
    if user_role not in ["admin", "admin_team"]:
        raise HTTPException(status_code=403, detail="Non autorizzato")


router = APIRouter(
    prefix="/insurance",
    tags=["insurance"]
)

# 🟢 Creazione Preventivo
@router.post("/preventivi", response_model=PreventivoResponse)
def crea_preventivo(
    preventivo: PreventivoCreate, 
    db: Session = Depends(get_db), 
    Authorize: AuthJWT = Depends(check_admin_or_admin_team)
):
    nuovo_preventivo = AssPreventivo(
        id_cliente=preventivo.id_cliente,
        id_prodotto=preventivo.id_prodotto,
        id_agenzia=preventivo.id_agenzia,
        id_compagnia=preventivo.id_compagnia,
        id_ramo=preventivo.id_ramo,
        id_frazionamento=preventivo.id_frazionamento,
        premio_totale=preventivo.premio_totale,
        premio_rata=preventivo.premio_rata,
        premio_competenza=preventivo.premio_competenza,
        id_admin=preventivo.id_admin,
        id_team=preventivo.id_team,
        modalita_pagamento_cliente=preventivo.modalita_pagamento_cliente,
        data_scadenza_validita=preventivo.data_scadenza_validita,
        data_accettazione_cliente=preventivo.data_accettazione_cliente,
        blob_url=preventivo.blob_url,
        stato=preventivo.stato,
        confermato_da_cliente=preventivo.confermato_da_cliente
    )
    db.add(nuovo_preventivo)
    db.commit()
    db.refresh(nuovo_preventivo)

    for garanzia in preventivo.garanzie:
        nuova_garanzia = AssPreventivoGaranzia(
            preventivo_id=nuovo_preventivo.id,
            garanzia_id=garanzia.garanzia_id
        )
        db.add(nuova_garanzia)

        # Gestione massimali/franchigie associati alla garanzia
        for mf_id in garanzia.massimali_franchigie:
            nuovo_mf = AssPreventivoGaranziaMF(
                prev_garanzia_id=nuova_garanzia.id,
                mf_id=mf_id
            )
            db.add(nuovo_mf)

    # Gestione rischi
    if preventivo.rischi:
        for rischio in preventivo.rischi:
            nuovo_rischio = AssPreventivoRischio(
                preventivo_id=nuovo_preventivo.id,
                descrizione=rischio.descrizione
            )
            db.add(nuovo_rischio)

    db.commit()

    return nuovo_preventivo

@router.post("/preventivi/conferma")
def conferma_preventivo(
    conferma: ConfermaPreventivo,
    db: Session = Depends(get_db),
    Authorize: AuthJWT = Depends(check_admin_or_admin_team)
):
    db_preventivo = db.query(AssPreventivo).filter(AssPreventivo.id == conferma.preventivo_id).first()
    if not db_preventivo:
        raise HTTPException(status_code=404, detail="Preventivo non trovato")

    db_conferma = AssPreventivoConferma(
        preventivo_id=conferma.preventivo_id,
        ip_cliente=conferma.ip_cliente,
        confermato=conferma.confermato,
        note=conferma.note
    )

    if conferma.confermato:
        db_preventivo.confermato_da_cliente = True
        db_preventivo.data_accettazione_cliente = datetime.now()

    db.add(db_conferma)
    db.commit()

    return {"status": "success", "confermato": conferma.confermato}


# 🟢 Conversione Preventivo → Polizza
@router.post("/polizze", response_model=PolizzaResponse)
def crea_polizza(
    polizza: PolizzaCreate,
    db: Session = Depends(get_db),
    Authorize: AuthJWT = Depends(check_admin_or_admin_team)
):
    db_preventivo = db.query(AssPreventivo).filter(AssPreventivo.id == polizza.preventivo_id).first()
    if not db_preventivo:
        raise HTTPException(status_code=404, detail="Preventivo non trovato")

    db_polizza = AssPolizza(
        preventivo_id=polizza.preventivo_id,
        numero_polizza=polizza.numero_polizza,
        data_decorrenza=polizza.data_decorrenza,
        data_emissione=datetime.now()
    )
    db_preventivo.stato = "trasformato_in_polizza"

    db.add(db_polizza)
    db.commit()
    db.refresh(db_polizza)
    return db_polizza


# 🟢 Gestione Incassi
@router.post("/incassi", response_model=IncassoResponse)
def crea_incasso(
    incasso: IncassoCreate,
    db: Session = Depends(get_db),
    Authorize: AuthJWT = Depends(check_admin_or_admin_team)
):
    db_polizza = db.query(AssPolizza).filter(AssPolizza.id == incasso.polizza_id).first()
    if not db_polizza:
        raise HTTPException(status_code=404, detail="Polizza non trovata")

    db_incasso = AssIncasso(
        polizza_id=incasso.polizza_id,
        importo=incasso.importo,
        metodo_pagamento=incasso.metodo_pagamento,
        data_incasso=incasso.data_incasso or datetime.now()
    )
    db.add(db_incasso)
    db.commit()
    db.refresh(db_incasso)
    return db_incasso


# 🟢 Lista preventivi
@router.get("/preventivi", response_model=List[PreventivoResponse])
def lista_preventivi(
    id_cliente: Optional[int] = None,
    stato: Optional[str] = None,
    db: Session = Depends(get_db),
    Authorize: AuthJWT = Depends(check_admin_or_admin_team)
):
    query = db.query(AssPreventivo)
    if id_cliente:
        query = query.filter(AssPreventivo.id_cliente == id_cliente)
    if stato:
        query = query.filter(AssPreventivo.stato == stato)
    return query.order_by(AssPreventivo.data_creazione.desc()).all()


# 🟢 Dettaglio preventivo
@router.get("/preventivi/{preventivo_id}")
def dettaglio_preventivo(
    preventivo_id: uuid.UUID,
    db: Session = Depends(get_db),
    Authorize: AuthJWT = Depends(check_admin_or_admin_team)
):
    preventivo = db.query(AssPreventivo).filter(AssPreventivo.id == preventivo_id).first()
    if not preventivo:
        raise HTTPException(status_code=404, detail="Preventivo non trovato")
    
    garanzie = db.query(AssPreventivoGaranzia).filter(AssPreventivoGaranzia.preventivo_id == preventivo_id).all()
    rischi = db.query(AssPreventivoRischio).filter(AssPreventivoRischio.preventivo_id == preventivo_id).all()
    
    return {
        "preventivo": preventivo,
        "garanzie": garanzie,
        "rischi": rischi
    }

# 🟢 Lista polizze
@router.get("/polizze", response_model=List[PolizzaResponse])
def lista_polizze(
    id_cliente: Optional[int] = None,
    db: Session = Depends(get_db),
    Authorize: AuthJWT = Depends(check_admin_or_admin_team)
):
    query = db.query(AssPolizza).join(AssPreventivo)
    if id_cliente:
        query = query.filter(AssPreventivo.id_cliente == id_cliente)
    return query.order_by(AssPolizza.data_emissione.desc()).all()


# 🟢 Dettaglio polizza
@router.get("/polizze/{polizza_id}", response_model=PolizzaResponse)
def dettaglio_polizza(
    polizza_id: uuid.UUID,
    db: Session = Depends(get_db),
    Authorize: AuthJWT = Depends(check_admin_or_admin_team)
):
    polizza = db.query(AssPolizza).filter(AssPolizza.id == polizza_id).first()
    if not polizza:
        raise HTTPException(status_code=404, detail="Polizza non trovata")
    return polizza


# 🟢 Lista incassi polizza
@router.get("/incassi/polizza/{polizza_id}", response_model=List[IncassoResponse])
def lista_incassi(
    polizza_id: uuid.UUID,
    db: Session = Depends(get_db),
    Authorize: AuthJWT = Depends(check_admin_or_admin_team)
):
    return db.query(AssIncasso).filter(AssIncasso.polizza_id == polizza_id).order_by(AssIncasso.data_incasso.desc()).all()


# 🟢 Aggiorna incasso
@router.put("/incassi/{incasso_id}", response_model=IncassoResponse)
def aggiorna_incasso(
    incasso_id: uuid.UUID,
    incasso: IncassoCreate,
    db: Session = Depends(get_db),
    Authorize: AuthJWT = Depends(check_admin_or_admin_team)
):
    db_incasso = db.query(AssIncasso).filter(AssIncasso.id == incasso_id).first()
    if not db_incasso:
        raise HTTPException(status_code=404, detail="Incasso non trovato")
    
    db_incasso.importo = incasso.importo
    db_incasso.metodo_pagamento = incasso.metodo_pagamento
    if incasso.data_incasso:
        db_incasso.data_incasso = incasso.data_incasso
    
    db.commit()
    db.refresh(db_incasso)
    return db_incasso
