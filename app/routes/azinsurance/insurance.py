from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime
from app.database import get_db
from app.routes.azinsurance.models_azinsurance import (
    AssPreventivo, AssPolizza, AssIncasso,
    AssPreventivoGaranzia, AssPreventivoRischio, AssPreventivoConferma
)
from app.routes.azinsurance.schemas_azinsurance import (
    PreventivoCreate, ConfermaPreventivo, PolizzaCreate, IncassoCreate,
    PreventivoResponse, PolizzaResponse, IncassoResponse
)
import uuid

router = APIRouter()

# 🟢 Creazione Preventivo
@router.post("/preventivi", response_model=PreventivoResponse)
def crea_preventivo(preventivo: PreventivoCreate, db: Session = Depends(get_db)):
    nuovo_preventivo = AssPreventivo(
        cliente_id=preventivo.cliente_id,
        prodotto_id=preventivo.prodotto_id,
        stato_id=preventivo.stato_id,
        frazionamento_id=preventivo.frazionamento_id,
        premio_totale=preventivo.premio_totale
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

    if preventivo.rischi:
        for rischio in preventivo.rischi:
            nuovo_rischio = AssPreventivoRischio(
                preventivo_id=nuovo_preventivo.id,
                descrizione=rischio.descrizione
            )
            db.add(nuovo_rischio)

    db.commit()
    return nuovo_preventivo

# 🟢 Conferma Preventivo
@router.post("/preventivi/conferma")
def conferma_preventivo(conferma: ConfermaPreventivo, db: Session = Depends(get_db)):
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
        db_preventivo.stato_id = 2  # stato confermato

    db.add(db_conferma)
    db.commit()

    return {"status": "success", "confermato": conferma.confermato}

# 🟢 Conversione Preventivo → Polizza
@router.post("/polizze", response_model=PolizzaResponse)
def crea_polizza(polizza: PolizzaCreate, db: Session = Depends(get_db)):
    db_preventivo = db.query(AssPreventivo).filter(AssPreventivo.id == polizza.preventivo_id).first()
    if not db_preventivo:
        raise HTTPException(status_code=404, detail="Preventivo non trovato")

    db_polizza = AssPolizza(
        preventivo_id=polizza.preventivo_id,
        numero_polizza=polizza.numero_polizza,
        data_decorrenza=polizza.data_decorrenza,
        data_emissione=datetime.now()
    )
    db_preventivo.stato_id = 3  # stato "trasformato in polizza"

    db.add(db_polizza)
    db.commit()
    db.refresh(db_polizza)
    return db_polizza

# 🟢 Gestione Incassi
@router.post("/incassi", response_model=IncassoResponse)
def crea_incasso(incasso: IncassoCreate, db: Session = Depends(get_db)):
    db_polizza = db.query(AssPolizza).filter(AssPolizza.id == incasso.polizza_id).first()
    if not db_polizza:
        raise HTTPException(status_code=404, detail="Polizza non trovata")

    db_incasso = AssIncasso(
        polizza_id=incasso.polizza_id,
        importo=incasso.importo,
        metodo_pagamento=incasso.metodo_pagamento,
        data_incasso=datetime.now()
    )
    db.add(db_incasso)
    db.commit()
    db.refresh(db_incasso)
    return db_incasso

# 🟢 Lista preventivi
@router.get("/preventivi", response_model=List[PreventivoResponse])
def lista_preventivi(cliente_id: Optional[int] = None, stato_id: Optional[int] = None, db: Session = Depends(get_db)):
    query = db.query(AssPreventivo)
    if cliente_id:
        query = query.filter(AssPreventivo.cliente_id == cliente_id)
    if stato_id:
        query = query.filter(AssPreventivo.stato_id == stato_id)
    return query.order_by(AssPreventivo.data_creazione.desc()).all()

# 🟢 Dettaglio preventivo
@router.get("/preventivi/{preventivo_id}")
def dettaglio_preventivo(preventivo_id: uuid.UUID, db: Session = Depends(get_db)):
    preventivo = db.query(AssPreventivo).filter(AssPreventivo.id == preventivo_id).first()
    if not preventivo:
        raise HTTPException(status_code=404, detail="Preventivo non trovato")
    garanzie = db.query(AssPreventivoGaranzia).filter(AssPreventivoGaranzia.preventivo_id == preventivo_id).all()
    rischi = db.query(AssPreventivoRischio).filter(AssPreventivoRischio.preventivo_id == preventivo_id).all()
    return {"preventivo": preventivo, "garanzie": garanzie, "rischi": rischi}

# 🟢 Lista polizze
@router.get("/polizze", response_model=List[PolizzaResponse])
def lista_polizze(cliente_id: Optional[int] = None, db: Session = Depends(get_db)):
    query = db.query(AssPolizza).join(AssPreventivo)
    if cliente_id:
        query = query.filter(AssPreventivo.cliente_id == cliente_id)
    return query.order_by(AssPolizza.data_emissione.desc()).all()

# 🟢 Dettaglio polizza
@router.get("/polizze/{polizza_id}", response_model=PolizzaResponse)
def dettaglio_polizza(polizza_id: uuid.UUID, db: Session = Depends(get_db)):
    polizza = db.query(AssPolizza).filter(AssPolizza.id == polizza_id).first()
    if not polizza:
        raise HTTPException(status_code=404, detail="Polizza non trovata")
    return polizza

# 🟢 Lista incassi polizza
@router.get("/incassi/polizza/{polizza_id}", response_model=List[IncassoResponse])
def lista_incassi(polizza_id: uuid.UUID, db: Session = Depends(get_db)):
    return db.query(AssIncasso).filter(AssIncasso.polizza_id == polizza_id).order_by(AssIncasso.data_incasso.desc()).all()

# 🟢 Aggiorna incasso
@router.put("/incassi/{incasso_id}", response_model=IncassoResponse)
def aggiorna_incasso(incasso_id: uuid.UUID, incasso: IncassoCreate, db: Session = Depends(get_db)):
    db_incasso = db.query(AssIncasso).filter(AssIncasso.id == incasso_id).first()
    if not db_incasso:
        raise HTTPException(status_code=404, detail="Incasso non trovato")
    db_incasso.importo = incasso.importo
    db_incasso.metodo_pagamento = incasso.metodo_pagamento
    db.commit()
    db.refresh(db_incasso)
    return db_incasso
