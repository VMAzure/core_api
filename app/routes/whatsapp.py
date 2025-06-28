from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel
from typing import Dict, List
from app.utils.twilio_client import send_whatsapp_template, send_whatsapp_message
from app.models import NltPipeline, NltPreventivi, Cliente, User, WhatsAppTemplate, NltMessaggiWhatsapp
from sqlalchemy.orm import Session
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
    utente_id = Authorize.get_jwt_subject()

    template = db.query(WhatsAppTemplate).filter_by(nome=data.template, attivo=True).first()
    if not template:
        raise HTTPException(status_code=400, detail="Template non riconosciuto o disattivo")

    pipeline = db.query(NltPipeline).filter_by(id=pipeline_id).first()
    if not pipeline or not pipeline.preventivo or not pipeline.preventivo.cliente or not pipeline.preventivo.cliente.telefono:
        raise HTTPException(status_code=404, detail="Numero telefono cliente non trovato")

    numero = f"whatsapp:{pipeline.preventivo.cliente.telefono.strip()}"

    sid = send_whatsapp_template(
        to=numero,
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
    utente_id = Authorize.get_jwt_subject()

    pipeline = db.query(NltPipeline).filter_by(id=pipeline_id).first()
    if not pipeline or not pipeline.preventivo or not pipeline.preventivo.cliente or not pipeline.preventivo.cliente.telefono:
        raise HTTPException(status_code=404, detail="Numero telefono cliente non trovato")

    numero = pipeline.preventivo.cliente.telefono.strip()
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

    if not sender or not message:
        raise HTTPException(status_code=400, detail="Messaggio non valido")

    numero = sender.replace("whatsapp:", "").strip()

    pipeline = (
        db.query(NltPipeline)
        .join(NltPreventivi, NltPipeline.preventivo_id == NltPreventivi.id)
        .join(Cliente, NltPreventivi.cliente_id == Cliente.id)
        .filter(Cliente.telefono == numero)
        .first()
    )

    if not pipeline:
        raise HTTPException(status_code=404, detail="Pipeline non trovata per questo numero")

    nuovo_log = NltMessaggiWhatsapp(
        pipeline_id=pipeline.id,
        mittente="cliente",
        messaggio=message,
        twilio_sid=msg_sid,
        template_usato=None,
        direzione="in",
        utente_id=None
    )
    db.add(nuovo_log)
    db.commit()

    logging.info(f"\U0001f4e9 Messaggio IN ricevuto da {numero}: {message}")

    return {"status": "ok"}
