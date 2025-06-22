from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, raiseload, joinedload
from uuid import UUID
from fastapi_jwt_auth import AuthJWT  
from fastapi import Body
from app.auth_helpers import is_admin_user, is_dealer_user, is_team_user, get_admin_id, get_dealer_id
from app.database import get_db
from app.models import NltPipeline, NltPipelineStati, NltPreventivi, User, CrmAzione, NltPipelineLog, SiteAdminSettings
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime, timedelta
from app.utils.calcola_scadenza_azione import calcola_scadenza_azione_intelligente
from fastapi.responses import RedirectResponse



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
    email_reminder_inviata: Optional[bool]         # ✅ NUOVO
    email_reminder_scheduled: Optional[datetime]   # ✅ NUOVO
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

    file_url: Optional[str]

    email: Optional[str]
    telefono: Optional[str]
    indirizzo: Optional[str]



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
    from app.auth_helpers import (
        is_admin_user, is_dealer_user,
        get_admin_id, get_dealer_id
    )

    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()

    user = db.query(User).filter(User.email == user_email).first()
    if not user:
        raise HTTPException(status_code=401, detail="Utente non trovato")

    user_id = user.id
    ruolo = user.role
    utenti_visibili = []

    if ruolo in ["admin", "admin_team"]:
        admin_id = get_admin_id(user)
        utenti_visibili.append(user_id)  # sempre se stesso
        if ruolo == "admin":
            team_ids = db.query(User.id).filter(User.parent_id == admin_id, User.role == "admin_team").all()
            utenti_visibili += [u.id for u in team_ids]

    elif ruolo in ["dealer", "dealer_team"]:
        dealer_id = get_dealer_id(user)
        utenti_visibili.append(user_id)
        if ruolo == "dealer":
            team_ids = db.query(User.id).filter(User.parent_id == dealer_id, User.role == "dealer_team").all()
            utenti_visibili += [u.id for u in team_ids]

    elif ruolo == "superadmin":
        utenti_visibili = db.query(User.id).all()
        utenti_visibili = [u.id for u in utenti_visibili]

    else:
        utenti_visibili = [user_id]  # fallback di sicurezza

    # Query pipeline
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

        output.append(PipelineItemOut(
            id=pipeline.id,
            preventivo_id=pipeline.preventivo_id,
            assegnato_a=pipeline.assegnato_a,
            stato_pipeline=pipeline.stato_pipeline,
            data_ultimo_contatto=pipeline.data_ultimo_contatto,
            prossima_azione=pipeline.prossima_azione,
            scadenza_azione=pipeline.scadenza_azione,
            email_reminder_inviata=pipeline.email_reminder_inviata,
            email_reminder_scheduled=pipeline.email_reminder_scheduled,

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
            note=preventivo.note,
            file_url=preventivo.file_url,

            email=cliente.email if cliente else None,
            telefono=cliente.telefono if cliente else None,
            indirizzo=cliente.indirizzo if cliente else None,

        ))

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

    # 🔍 Verifica se già attiva
    esistente = db.query(NltPipeline).filter(NltPipeline.preventivo_id == payload.preventivo_id).first()
    if esistente:
        raise HTTPException(status_code=400, detail="Pipeline già attiva per questo preventivo")

    # 🔍 Recupera il preventivo
    preventivo = db.query(NltPreventivi).filter(NltPreventivi.id == payload.preventivo_id).first()
    if not preventivo:
        raise HTTPException(status_code=404, detail="Preventivo non trovato")

    assegnato_a = preventivo.preventivo_assegnato_a
    if assegnato_a is None:
        raise HTTPException(status_code=400, detail="Il preventivo non ha un assegnatario")

    # ✅ Logica autorizzazione
    autorizzato = False

    if is_admin_user(user):
        admin_id = get_admin_id(user)
        if user.id == assegnato_a:
            autorizzato = True
        else:
            team_ids = db.query(User.id).filter(
                User.parent_id == admin_id,
                User.role == "admin_team"
            ).all()
            if assegnato_a in [u.id for u in team_ids]:
                autorizzato = True

    elif is_dealer_user(user):
        dealer_id = get_dealer_id(user)
        if user.id == assegnato_a:
            autorizzato = True
        else:
            team_ids = db.query(User.id).filter(
                User.parent_id == dealer_id,
                User.role == "dealer_team"
            ).all()
            if assegnato_a in [u.id for u in team_ids]:
                autorizzato = True

    else:
        # Fallback: solo se stesso
        if user.id == assegnato_a:
            autorizzato = True

    if not autorizzato:
        raise HTTPException(status_code=403, detail="Non autorizzato ad attivare la pipeline per questo preventivo")

    # ✅ Crea nuova pipeline
    nuova_pipeline = NltPipeline(
        preventivo_id=payload.preventivo_id,
        assegnato_a=assegnato_a,
        stato_pipeline="preventivo",
        data_ultimo_contatto=datetime.utcnow(),
        scadenza_azione=calcola_scadenza_azione_intelligente(datetime.utcnow()),
        email_reminder_inviata=False,
        email_reminder_scheduled=None
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

class PipelineLogCreate(BaseModel):
    pipeline_id: UUID
    tipo_azione: str
    note: Optional[str] = None

@router.post("/log")
def crea_log_pipeline(payload: PipelineLogCreate, db: Session = Depends(get_db), Authorize: AuthJWT = Depends()):
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()

    user = db.query(User).filter(User.email == user_email).first()
    if not user:
        raise HTTPException(status_code=401, detail="Utente non trovato")

    nuovo_log = NltPipelineLog(
        pipeline_id=payload.pipeline_id,
        tipo_azione=payload.tipo_azione,
        note=payload.note,
        data_evento=datetime.utcnow(),
        utente_id=user.id
    )

    db.add(nuovo_log)
    db.commit()
    db.refresh(nuovo_log)

    return {"message": "Log registrato", "log_id": nuovo_log.id}

class PipelineLogOut(BaseModel):
    id: UUID
    pipeline_id: UUID
    tipo_azione: str
    note: Optional[str]
    data_evento: datetime
    utente_id: Optional[int]  # ✅ ORA ACCETTA None

    class Config:
        orm_mode = True

@router.get("/log/{pipeline_id}", response_model=List[PipelineLogOut])
def get_log_per_pipeline(pipeline_id: UUID, db: Session = Depends(get_db)):
    logs = (
        db.query(NltPipelineLog)
        .filter(NltPipelineLog.pipeline_id == pipeline_id)
        .order_by(NltPipelineLog.data_evento.desc())
        .all()
    )

    return logs

@router.get("/collegate/{pipeline_id}", response_model=List[PipelineItemOut])
def get_pipeline_collegate(pipeline_id: UUID, db: Session = Depends(get_db)):
    # Recupera pipeline attuale
    pipeline = db.query(NltPipeline).filter(NltPipeline.id == pipeline_id).first()
    if not pipeline:
        raise HTTPException(status_code=404, detail="Pipeline non trovata")

    # Recupera preventivo
    preventivo = db.query(NltPreventivi).filter(NltPreventivi.id == pipeline.preventivo_id).first()
    if not preventivo:
        raise HTTPException(status_code=404, detail="Preventivo non trovato")

    # Recupera tutte le pipeline del cliente (escluse questa)
    pipeline_collegate = (
        db.query(NltPipeline, NltPreventivi)
        .join(NltPreventivi, NltPipeline.preventivo_id == NltPreventivi.id)
        .filter(
            NltPreventivi.cliente_id == preventivo.cliente_id,
            NltPipeline.id != pipeline.id
        )
        .order_by(NltPipeline.created_at.desc())
        .all()
    )

    risultati = []
    for p, prev in pipeline_collegate:
        cliente = prev.cliente
        risultati.append(PipelineItemOut(
            id=p.id,
            preventivo_id=p.preventivo_id,
            assegnato_a=p.assegnato_a,
            stato_pipeline=p.stato_pipeline,
            data_ultimo_contatto=p.data_ultimo_contatto,
            prossima_azione=p.prossima_azione,
            scadenza_azione=p.scadenza_azione,
            email_reminder_inviata=p.email_reminder_inviata,
            email_reminder_scheduled=p.email_reminder_scheduled,
            note_commerciali=p.note_commerciali,
            created_at=p.created_at,
            updated_at=p.updated_at,
            cliente_nome=cliente.nome if cliente else None,
            cliente_cognome=cliente.cognome if cliente else None,
            ragione_sociale=cliente.ragione_sociale if cliente else None,
            tipo_cliente=cliente.tipo_cliente if cliente else None,
            marca=prev.marca,
            modello=prev.modello,
            durata=prev.durata,
            km_totali=prev.km_totali,
            anticipo=prev.anticipo,
            canone=prev.canone,
            player=prev.player,
            note=prev.note,
            file_url=prev.file_url,
            email=cliente.email if cliente else None,
            telefono=cliente.telefono if cliente else None,
            indirizzo=cliente.indirizzo if cliente else None,
        ))

    return risultati

@router.get("/concludi/{pipeline_id}")
def concludi_pipeline_pubblica(pipeline_id: UUID, db: Session = Depends(get_db)):
    pipeline = db.query(NltPipeline).filter(NltPipeline.id == pipeline_id).first()
    if not pipeline:
        raise HTTPException(status_code=404, detail="Pipeline non trovata")

    if pipeline.stato_pipeline == "concluso":
        return RedirectResponse(url="https://www.azcore.it/")

    pipeline.stato_pipeline = "perso"
    pipeline.updated_at = datetime.utcnow()

    db.add(NltPipelineLog(
        pipeline_id=pipeline.id,
        tipo_azione="rifiutato",
        note="Utente ha concluso la pipeline via link pubblico",
        data_evento=datetime.utcnow(),
        utente_id=None
    ))

    # ✅ Recupera slug come da logica corretta
    assegnatario = db.query(User).filter_by(id=pipeline.assegnato_a).first()
    admin_id = assegnatario.parent_id or assegnatario.id
    admin = db.query(User).filter_by(id=admin_id).first()

    dealer_settings = db.query(SiteAdminSettings).filter_by(dealer_id=assegnatario.id).first()
    if not dealer_settings:
        dealer_settings = db.query(SiteAdminSettings).filter_by(admin_id=admin.id).order_by(SiteAdminSettings.id.asc()).first()

    slug = dealer_settings.slug if dealer_settings and dealer_settings.slug else "default"
    url_vetrina = f"https://www.azcore.it/vetrina-offerte/{slug}"

    db.commit()

    return RedirectResponse(url=url_vetrina, status_code=302)


class RichiestaAppuntamentoInput(BaseModel):
    data_preferita: str  # formato ISO string
    modalita: str
    note: Optional[str] = None


@router.post("/richiesta-appuntamento/{pipeline_id}")
def richiesta_appuntamento_pubblica(
    pipeline_id: UUID,
    payload: RichiestaAppuntamentoInput,
    db: Session = Depends(get_db)
):
    pipeline = db.query(NltPipeline).filter(NltPipeline.id == pipeline_id).first()
    if not pipeline:
        raise HTTPException(status_code=404, detail="Pipeline non trovata")

    # Componi le note
    nota_finale = (
        "Richiesta contatto pubblico\n"
        f"Modalità: {payload.modalita.strip().capitalize()}\n"
        f"Data preferita: {payload.data_preferita.strip()}\n"
        f"Note: \"{payload.note.strip()}\"" if payload.note else "Note: (non specificate)"
    )

    # Aggiorna pipeline
    pipeline.stato_pipeline = "negoziazione"
    pipeline.note_commerciali = nota_finale
    pipeline.updated_at = datetime.utcnow()

    # Inserisci log
    log = NltPipelineLog(
        pipeline_id=pipeline.id,
        tipo_azione="richiesta_contatto",
        note=nota_finale,
        data_evento=datetime.utcnow(),
        utente_id=None  # anonimo
    )

    db.add(log)
    db.commit()

    return {"message": "Richiesta contatto registrata con successo"}