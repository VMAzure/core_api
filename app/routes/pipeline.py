from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from uuid import UUID
from fastapi_jwt_auth import AuthJWT  
from fastapi import Body

from app.database import get_db
from app.models import NltPipeline, NltPipelineStati, NltPreventivi, User
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
    id: str
    preventivo_id: str
    assegnato_a: int
    stato_pipeline: str
    data_ultimo_contatto: Optional[datetime]
    prossima_azione: Optional[str]
    scadenza_azione: Optional[datetime]
    note_commerciali: Optional[str]
    created_at: datetime
    updated_at: datetime


class PipelineStatoOut(BaseModel):
    codice: str
    descrizione: str
    ordine: int


# === ENDPOINTS ===

@router.get("/", response_model=List[PipelineItemOut])
def get_pipeline(Authorize: AuthJWT = Depends(), db: Session = Depends(get_db)):
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()
    user = db.query(User).filter(User.email == user_email).first()
    if not user:
        raise HTTPException(status_code=401, detail="Utente non trovato")
    user_id = user.id

    return db.query(NltPipeline).filter(NltPipeline.assegnato_a == user_id).all()



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
    return db.query(NltPipelineStati).order_by(NltPipelineStati.ordine).all()


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
        stato_pipeline="nuovo",
        data_ultimo_contatto=datetime.utcnow()
    )

    db.add(nuova_pipeline)
    db.commit()
    db.refresh(nuova_pipeline)
    return nuova_pipeline
