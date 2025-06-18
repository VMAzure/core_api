from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, raiseload, joinedload
from uuid import UUID
from fastapi_jwt_auth import AuthJWT  
from fastapi import Body
from app.auth_helpers import is_admin_user, is_dealer_user, is_team_user, get_admin_id, get_dealer_id
from app.database import get_db
from app.models import NltPipeline, NltPipelineStati, NltPreventivi, User, CrmAzione
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime

router = APIRouter(prefix="/api/pipeline", tags=["Pipeline"])

# === SCHEMI ===

class PipelineItemUpdate(BaseModel):
    stato_pipeline: Optional[str] = None
    note_commerciali: Optional[str] = None
    prossima_azione: Optional[str] = None
    scadenza_azione: Optional[datetime] = None


class PipelineItemOut(BaseModel):
    id: UUID
    preventivo_id: UUID
    assegnato_a: int
    stato_pipeline: str
    data_ultimo_contatto: Optional[datetime]
    prossima_azione: Optional[str]
    scadenza_azione: Optional[datetime]
    note_commerciali: Optional[str]
    created_at: datetime
    updated_at: datetime

    cliente_nome: Optional[str]
    cliente_cognome: Optional[str]
    ragione_sociale: Optional[str]
    tipo_cliente: Optional[str]

    marca: Optional[str]
    modello: Optional[str]
    durata: Optional[int]
    km_totali: Optional[int]
    anticipo: Optional[float]
    canone: Optional[float]
    player: Optional[str]
    note: Optional[str]

    class Config:
        orm_mode = True



class PipelineStatoOut(BaseModel):
    codice: str
    descrizione: str
    ordine: int

    class Config:
        orm_mode = True


# === ENDPOINTS ===



@router.get("/", response_model=List[PipelineItemOut])
def get_pipeline(Authorize: AuthJWT = Depends(), db: Session = Depends(get_db)):
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()
    user = db.query(User).filter(User.email == user_email).first()
    if not user:
        raise HTTPException(status_code=401, detail="Utente non trovato")

    user_id = user.id
    utenti_visibili = []

    if is_admin_user(user):
        admin_id = get_admin_id(user)
        utenti_visibili = [admin_id]
        # Prende tutti gli user creati da quell'admin (admin_team)
        team_ids = db.query(User.id).filter(User.parent_id == admin_id).all()
        utenti_visibili += [u.id for u in team_ids]

    elif is_dealer_user(user):
        dealer_id = get_dealer_id(user)
        utenti_visibili = [dealer_id]
        team_ids = db.query(User.id).filter(User.parent_id == dealer_id).all()
        utenti_visibili += [u.id for u in team_ids]

    else:
        # Fallback: solo se stesso
        utenti_visibili = [user_id]

    pipeline_items = (
        db.query(NltPipeline, NltPreventivi)
        .join(NltPreventivi, NltPipeline.preventivo_id == NltPreventivi.id)
        .options(joinedload(NltPipeline.preventivo).joinedload(NltPreventivi.cliente))
        .filter(NltPipeline.assegnato_a.in_(utenti_visibili))
        .all()
    )

    output = []
    for pipeline, preventivo in pipeline_items:
        cliente = preventivo.cliente

        item = PipelineItemOut(
            id=pipeline.id,
            preventivo_id=pipeline.preventivo_id,
            assegnato_a=pipeline.assegnato_a,
            stato_pipeline=pipeline.stato_pipeline,
            data_ultimo_contatto=pipeline.data_ultimo_contatto,
            prossima_azione=pipeline.prossima_azione,
            scadenza_azione=pipeline.scadenza_azione,
            note_commerciali=pipeline.note_commerciali,
            created_at=pipeline.created_at,
            updated_at=pipeline.updated_at,

            cliente_nome=cliente.nome if cliente else None,
            cliente_cognome=cliente.cognome if cliente else None,
            ragione_sociale=cliente.ragione_sociale if cliente else None,
            tipo_cliente=cliente.tipo_cliente if cliente else None,

            marca=preventivo.marca,
            modello=preventivo.modello,
            durata=preventivo.durata,
            km_totali=preventivo.km_totali,
            anticipo=preventivo.anticipo,
            canone=preventivo.canone,
            player=preventivo.player,
            note=preventivo.note
        )

        output.append(item)

    return output


@router.patch("/{id}", response_model=PipelineItemOut)
def update_pipeline(id: str, payload: PipelineItemUpdate, Authorize: AuthJWT = Depends(), db: Session = Depends(get_db)):
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()
    user = db.query(User).filter(User.email == user_email).first()
    if not user:
        raise HTTPException(status_code=401, detail="Utente non trovato")
    user_id = user.id

    pipeline_item = db.query(NltPipeline).filter(NltPipeline.id == id).first()
    if not pipeline_item:
        raise HTTPException(status_code=404, detail="Pipeline item not found")

    # Autorizzazione: deve essere l'assegnato o il suo admin
    preventivo = db.query(NltPreventivi).filter(NltPreventivi.id == pipeline_item.preventivo_id).first()
    if not preventivo:
        raise HTTPException(status_code=404, detail="Preventivo non trovato")

    if pipeline_item.assegnato_a != user_id and user.role != "admin":
        raise HTTPException(status_code=403, detail="Non autorizzato a modificare questa pipeline")

    for field, value in payload.dict(exclude_unset=True).items():
        setattr(pipeline_item, field, value)

    pipeline_item.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(pipeline_item)
    return pipeline_item


@router.get("/stati", response_model=List[PipelineStatoOut])
def get_pipeline_stati(db: Session = Depends(get_db)):
    stati = db.query(NltPipelineStati).order_by(NltPipelineStati.ordine).all()
    return [PipelineStatoOut.from_orm(s).dict() for s in stati]



class PipelineCreateRequest(BaseModel):
    preventivo_id: UUID


@router.post("/attiva", response_model=PipelineItemOut)
def attiva_pipeline(
    payload: PipelineCreateRequest,
    db: Session = Depends(get_db),
    Authorize: AuthJWT = Depends()
):
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()
    user = db.query(User).filter(User.email == user_email).first()
    if not user:
        raise HTTPException(status_code=401, detail="Utente non trovato")
    user_id = user.id


    esistente = db.query(NltPipeline).filter(NltPipeline.preventivo_id == payload.preventivo_id).first()
    if esistente:
        raise HTTPException(status_code=400, detail="Pipeline già attiva per questo preventivo")

    preventivo = db.query(NltPreventivi).filter(NltPreventivi.id == payload.preventivo_id).first()
    if not preventivo:
        raise HTTPException(status_code=404, detail="Preventivo non trovato")

    assegnato_a = preventivo.preventivo_assegnato_a
    creato_da = preventivo.creato_da

    if assegnato_a is None:
        raise HTTPException(status_code=400, detail="Il preventivo non ha un assegnatario")

    if user_id != assegnato_a and user_id != creato_da:
        raise HTTPException(status_code=403, detail="Non autorizzato ad attivare la pipeline per questo preventivo")

    nuova_pipeline = NltPipeline(
        preventivo_id=payload.preventivo_id,
        assegnato_a=assegnato_a,
        stato_pipeline="preventivo",
        data_ultimo_contatto=datetime.utcnow()
    )

    db.add(nuova_pipeline)
    db.commit()
    db.refresh(nuova_pipeline)
    return nuova_pipeline

class CrmAzioneOut(BaseModel):
    id: int
    stato_codice: str
    descrizione: str
    ordine: int

    class Config:
        orm_mode = True

@router.get("/azioni/{stato_codice}", response_model=List[CrmAzioneOut])
def get_azioni_per_stato(stato_codice: str, db: Session = Depends(get_db)):
    azioni = (
        db.query(CrmAzione)
        .filter(CrmAzione.stato_codice == stato_codice)
        .order_by(CrmAzione.ordine)
        .all()
    )
    return azioni
