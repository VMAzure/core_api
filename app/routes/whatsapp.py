from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel
from typing import Dict, List
from app.utils.twilio_client import send_whatsapp_template, send_whatsapp_message
from app.models import NltPipeline, NltPreventivi, Cliente, User, WhatsAppTemplate, NltMessaggiWhatsapp, WhatsappSessione
from sqlalchemy.orm import Session
from sqlalchemy import func, or_
from app.database import get_db
from fastapi_jwt_auth import AuthJWT
import logging
import json
from datetime import datetime

router = APIRouter(prefix="/api/whatsapp", tags=["WhatsApp"])

class TemplateRequest(BaseModel):
    template: str
    variables: Dict[str, str]  # Esempio: {"1": "Mario", "2": "Valerio"...}

class FreeMessageRequest(BaseModel):
    messaggio: str

@router.post("/send-template/{pipeline_id}")
def invia_template_whatsapp(
    pipeline_id: str,
    data: TemplateRequest,
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    Authorize.jwt_required()
    utente_email = Authorize.get_jwt_subject()
    utente = db.query(User).filter_by(email=utente_email).first()
    if not utente:
        raise HTTPException(status_code=404, detail="Utente non trovato")
    utente_id = utente.id

    template = db.query(WhatsAppTemplate).filter_by(nome=data.template, attivo=True).first()
    if not template:
        raise HTTPException(status_code=400, detail="Template non riconosciuto o disattivo")

    pipeline = db.query(NltPipeline).filter_by(id=pipeline_id).first()
    if not pipeline or not pipeline.preventivo or not pipeline.preventivo.cliente or not pipeline.preventivo.cliente.telefono:
        raise HTTPException(status_code=404, detail="Numero telefono cliente non trovato")

    numero = pipeline.preventivo.cliente.telefono.strip()
    if not numero.startswith("+"):
        numero = "+39" + numero
    wa_numero = f"whatsapp:{numero}"

    sid = send_whatsapp_template(
        to=wa_numero,
        content_sid=template.content_sid,
        content_variables=data.variables
    )


    if not sid:
        raise HTTPException(status_code=500, detail="Errore invio messaggio WhatsApp")

    messaggio_testo = template.descrizione or "Messaggio inviato tramite template"

    nuovo_log = NltMessaggiWhatsapp(
        pipeline_id=pipeline.id,
        mittente="utente",
        messaggio=messaggio_testo,
        twilio_sid=sid,
        template_usato=template.nome,
        direzione="out",
        utente_id=utente_id
    )
    db.add(nuovo_log)
    db.commit()

    logging.info(f"\U0001f4e4 Template '{data.template}' inviato da utente {utente_id} alla pipeline {pipeline_id}")

    return {
        "status": "ok",
        "sid": sid,
        "numero": numero,
        "template": data.template
    }


@router.post("/send-free/{pipeline_id}")
def invia_messaggio_libero(
    pipeline_id: str,
    data: FreeMessageRequest,
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    Authorize.jwt_required()
    utente_email = Authorize.get_jwt_subject()
    utente = db.query(User).filter_by(email=utente_email).first()
    if not utente:
        raise HTTPException(status_code=404, detail="Utente non trovato")
    utente_id = utente.id


    pipeline = db.query(NltPipeline).filter_by(id=pipeline_id).first()
    if not pipeline or not pipeline.preventivo or not pipeline.preventivo.cliente or not pipeline.preventivo.cliente.telefono:
        raise HTTPException(status_code=404, detail="Numero telefono cliente non trovato")

    numero = pipeline.preventivo.cliente.telefono.strip()
    if not numero.startswith("+"):
        numero = "+39" + numero
    wa_numero = f"whatsapp:{numero}"


    sid = send_whatsapp_message(
        to=wa_numero,
        body=data.messaggio.strip()
    )

    if not sid:
        raise HTTPException(status_code=500, detail="Errore invio messaggio WhatsApp")

    print(f"📤 Log WhatsApp in DB — SID salvato: {sid} → Numero: {numero}")

    nuovo_log = NltMessaggiWhatsapp(
        pipeline_id=pipeline.id,
        mittente="utente",
        messaggio=data.messaggio.strip(),
        twilio_sid=sid,
        template_usato=None,
        direzione="out",
        utente_id=utente_id
    )
    db.add(nuovo_log)
    db.commit()

    logging.info(f"💬 Messaggio libero inviato da utente {utente_id} alla pipeline {pipeline_id}")

    return {
        "status": "ok",
        "sid": sid,
        "numero": numero,
        "messaggio": data.messaggio
    }


@router.get("/messaggi/{pipeline_id}")
def get_messaggi_pipeline(
    pipeline_id: str,
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    Authorize.jwt_required()

    messaggi = (
        db.query(NltMessaggiWhatsapp)
        .filter_by(pipeline_id=pipeline_id)
        .order_by(NltMessaggiWhatsapp.data_invio.asc())
        .all()
    )

    return [
        {
            "id": str(m.id),
            "mittente": m.mittente,
            "messaggio": m.messaggio,
            "data_invio": m.data_invio.isoformat(),
            "direzione": m.direzione,
            "template_usato": m.template_usato,
            "twilio_sid": m.twilio_sid,
            "utente_id": m.utente_id,
            "stato_messaggio": m.stato_messaggio,
        }
        for m in messaggi
    ]

@router.get("/messaggi-sessione/{sessione_id}")
def get_messaggi_sessione(
    sessione_id: str,
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    Authorize.jwt_required()

    messaggi = (
        db.query(NltMessaggiWhatsapp)
        .filter_by(sessione_id=sessione_id)
        .order_by(NltMessaggiWhatsapp.data_invio.asc())
        .all()
    )

    return [
        {
            "id": str(m.id),
            "mittente": m.mittente,
            "messaggio": m.messaggio,
            "data_invio": m.data_invio.isoformat(),
            "direzione": m.direzione,
            "template_usato": m.template_usato,
            "twilio_sid": m.twilio_sid,
            "utente_id": m.utente_id,
            "stato_messaggio": m.stato_messaggio
        }
        for m in messaggi
    ]


@router.post("/log-inbound")
async def log_messaggio_inbound(
    request: Request,
    db: Session = Depends(get_db)
):
    form = await request.form()
    sender = form.get("From")
    message = form.get("Body")
    msg_sid = form.get("MessageSid")
    timestamp = datetime.utcnow()

    print("📩 INBOUND DEBUG — From:", sender, "| Body:", message)

    if not sender or not message:
        raise HTTPException(status_code=400, detail="Messaggio non valido")

    numero = sender.replace("whatsapp:", "").strip()
    if not numero.startswith("+"):
        numero = "+39" + numero

    # Cerca cliente tramite numero normalizzato
    cliente = (
        db.query(Cliente)
        .filter(func.replace(Cliente.telefono, '+39', '') == numero.replace('+39', ''))
        .first()
    )

    if not cliente:
        print("❌ Nessun cliente trovato per numero:", numero)
        raise HTTPException(status_code=404, detail="Cliente non trovato")

    # Cerca o crea la sessione
    sessione = (
        db.query(WhatsappSessione)
        .filter_by(cliente_id=cliente.id)
        .first()
    )

    if not sessione:
        sessione = WhatsappSessione(
            cliente_id=cliente.id,
            numero=numero
        )
        db.add(sessione)
        db.flush()  # per ottenere sessione.id

    # Logga il messaggio
    nuovo_log = NltMessaggiWhatsapp(
        sessione_id=sessione.id,
        mittente="cliente",
        messaggio=message,
        twilio_sid=msg_sid,
        template_usato=None,
        direzione="in",
        utente_id=None
    )
    db.add(nuovo_log)
    db.commit()

    logging.info(f"📨 Messaggio IN salvato — Cliente: {cliente.id} | Sessione: {sessione.id}")

    return {"status": "ok"}

@router.get("/sessioni")
def get_lista_sessioni(
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    Authorize.jwt_required()
    email = Authorize.get_jwt_subject()

    utente = db.query(User).filter_by(email=email).first()
    if not utente:
        raise HTTPException(status_code=404, detail="Utente non trovato")

    sessioni_query = db.query(WhatsappSessione).join(Cliente, WhatsappSessione.cliente_id == Cliente.id)

    if utente.role in ["admin_team", "dealer_team"]:
        # Solo i clienti assegnati a me
        sessioni_query = sessioni_query.filter(Cliente.dealer_id == utente.id)
    elif utente.role in ["admin", "dealer"]:
        membri_team = db.query(User.id).filter(User.parent_id == utente.id).subquery()
        sessioni_query = sessioni_query.filter(
            or_(
                Cliente.dealer_id == utente.id,
                Cliente.dealer_id.in_(membri_team)
            )
        )

    else:
        raise HTTPException(status_code=403, detail="Ruolo non autorizzato")

    sessioni = sessioni_query.order_by(WhatsappSessione.ultimo_aggiornamento.desc()).all()

    risposta = []
    for s in sessioni:
        ultimo = (
            db.query(NltMessaggiWhatsapp)
            .filter(NltMessaggiWhatsapp.sessione_id == s.id)
            .order_by(NltMessaggiWhatsapp.data_invio.desc())
            .first()
        )

        non_letti = (
            db.query(func.count())
            .select_from(NltMessaggiWhatsapp)
            .filter_by(sessione_id=s.id, direzione="in", stato_messaggio=None)
            .scalar()
        )

        cliente = s.cliente
        nome = cliente.ragione_sociale or f"{cliente.nome} {cliente.cognome}"

        risposta.append({
            "sessione_id": str(s.id),
            "cliente_nome": nome,
            "numero": s.numero,
            "ultimo_messaggio": ultimo.messaggio if ultimo else "",
            "data_ultima_attivita": s.ultimo_aggiornamento.isoformat(),
            "non_letti": non_letti
        })

    return risposta
