from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel
from typing import Dict, List
from app.utils.twilio_client import send_whatsapp_template, send_whatsapp_message
from app.models import WhatsappSessione, NltMessaggiWhatsapp, Cliente, User, WhatsAppTemplate
from sqlalchemy.orm import Session
from sqlalchemy import func, or_, select
from app.database import get_db
from fastapi_jwt_auth import AuthJWT
import logging
from datetime import datetime
from app.auth_helpers import is_admin_user, is_dealer_user, get_admin_id, get_dealer_id
import os
import requests


router = APIRouter(prefix="/api/whatsapp", tags=["WhatsApp"])

class TemplateRequest(BaseModel):
    template: str
    variables: Dict[str, str]

class FreeMessageRequest(BaseModel):
    messaggio: str

@router.post("/sessioni/{sessione_id}/send-template")
def invia_template_whatsapp(
    sessione_id: str,
    data: TemplateRequest,
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    Authorize.jwt_required()
    utente = db.query(User).filter_by(email=Authorize.get_jwt_subject()).first()
    if not utente:
        raise HTTPException(404, detail="Utente non trovato")

    template = db.query(WhatsAppTemplate).filter_by(nome=data.template, attivo=True).first()
    if not template:
        raise HTTPException(400, detail="Template non valido o disattivo")

    sessione = db.query(WhatsappSessione).filter_by(id=sessione_id).first()
    if not sessione or not sessione.cliente or not sessione.cliente.telefono:
        raise HTTPException(404, detail="Numero telefono cliente non trovato")

    numero = sessione.cliente.telefono.strip()
    if not numero.startswith("+"):
        numero = "+39" + numero
    wa_numero = f"whatsapp:{numero}"

    sid = send_whatsapp_template(
        to=wa_numero,
        content_sid=template.content_sid,
        content_variables=data.variables
    )

    if not sid:
        raise HTTPException(500, detail="Errore invio messaggio WhatsApp")

    nuovo_log = NltMessaggiWhatsapp(
        sessione_id=sessione.id,
        mittente="utente",
        messaggio=template.descrizione or "Messaggio inviato tramite template",
        twilio_sid=sid,
        template_usato=template.nome,
        direzione="out",
        utente_id=utente.id
    )
    sessione.ultimo_aggiornamento = datetime.utcnow()
    db.add(nuovo_log)
    db.commit()

    return {"status": "ok", "sid": sid, "numero": numero, "template": data.template}

@router.post("/sessioni/{sessione_id}/send-free")
def invia_messaggio_libero(
    sessione_id: str,
    data: FreeMessageRequest,
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    Authorize.jwt_required()
    utente = db.query(User).filter_by(email=Authorize.get_jwt_subject()).first()
    if not utente:
        raise HTTPException(404, detail="Utente non trovato")

    sessione = db.query(WhatsappSessione).filter_by(id=sessione_id).first()
    if not sessione or not sessione.cliente or not sessione.cliente.telefono:
        raise HTTPException(404, detail="Numero telefono cliente non trovato")

    numero = sessione.cliente.telefono.strip()
    if not numero.startswith("+"):
        numero = "+39" + numero
    wa_numero = f"whatsapp:{numero}"

    sid = send_whatsapp_message(
        to=wa_numero,
        body=data.messaggio.strip()
    )

    if not sid:
        raise HTTPException(500, detail="Errore invio messaggio WhatsApp")

    nuovo_log = NltMessaggiWhatsapp(
        sessione_id=sessione.id,
        mittente="utente",
        messaggio=data.messaggio.strip(),
        twilio_sid=sid,
        template_usato=None,
        direzione="out",
        utente_id=utente.id
    )
    sessione.ultimo_aggiornamento = datetime.utcnow()
    db.add(nuovo_log)
    db.commit()

    return {"status": "ok", "sid": sid, "numero": numero, "messaggio": data.messaggio}

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

    if not sender or not message:
        raise HTTPException(status_code=400, detail="Messaggio non valido")

    numero = sender.replace("whatsapp:", "").strip()
    if not numero.startswith("+"):
        numero = "+39" + numero

    cliente = (
        db.query(Cliente)
        .filter(func.replace(Cliente.telefono, '+39', '') == numero.replace('+39', ''))
        .first()
    )

    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente non trovato")

    sessione = db.query(WhatsappSessione).filter_by(cliente_id=cliente.id).first()
    if not sessione:
        sessione = WhatsappSessione(cliente_id=cliente.id, numero=numero)
        db.add(sessione)
        db.flush()

    nuovo_log = NltMessaggiWhatsapp(
        sessione_id=sessione.id,
        mittente="cliente",
        messaggio=message,
        twilio_sid=msg_sid,
        template_usato=None,
        direzione="in",
        utente_id=None
    )
    sessione.ultimo_aggiornamento = datetime.utcnow()
    db.add(nuovo_log)
    db.commit()

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

    if is_dealer_user(utente):
        dealer_id = get_dealer_id(utente)
        sessioni_query = sessioni_query.filter(Cliente.dealer_id == dealer_id)

    elif is_admin_user(utente):
        admin_id = get_admin_id(utente)
        membri_team_subq = select(User.id).where(User.parent_id == admin_id)
        sessioni_query = sessioni_query.filter(
            or_(
                Cliente.dealer_id == admin_id,
                Cliente.dealer_id.in_(membri_team_subq)
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


@router.get("/messaggi-sessione/{sessione_id}/since/{timestamp}")
def get_nuovi_messaggi(sessione_id: str, timestamp: str, Authorize: AuthJWT = Depends(), db: Session = Depends(get_db)):
    Authorize.jwt_required()
    try:
        dt = datetime.fromisoformat(timestamp)
    except ValueError:
        raise HTTPException(400, detail="Formato timestamp non valido")

    messaggi = (
        db.query(NltMessaggiWhatsapp)
        .filter(
            NltMessaggiWhatsapp.sessione_id == sessione_id,
            NltMessaggiWhatsapp.data_invio > dt
        )
        .order_by(NltMessaggiWhatsapp.data_invio.asc())
        .all()
    )

    return [{
        "id": str(m.id),
        "mittente": m.mittente,
        "messaggio": m.messaggio,
        "data_invio": m.data_invio.isoformat(),
        "direzione": m.direzione,
        "template_usato": m.template_usato,
        "twilio_sid": m.twilio_sid,
        "utente_id": m.utente_id,
        "stato_messaggio": m.stato_messaggio
    } for m in messaggi]

class WhatsAppTemplateOut(BaseModel):
    nome: str
    content_sid: str

@router.get("/templates", response_model=List[WhatsAppTemplateOut])
def get_templates(
    db: Session = Depends(get_db),
    Authorize: AuthJWT = Depends()
):
    Authorize.jwt_required()
    templates = (
        db.query(WhatsAppTemplate)
        .filter_by(attivo=True)
        .order_by(WhatsAppTemplate.nome.asc())
        .all()
    )
    return [{"nome": t.nome, "content_sid": t.content_sid} for t in templates]

@router.post("/sync-templates")
def sync_twilio_templates(
    db: Session = Depends(get_db),
    Authorize: AuthJWT = Depends()
):
    Authorize.jwt_required()

    # 🔐 Opzionale: limita agli admin
    utente = db.query(User).filter_by(email=Authorize.get_jwt_subject()).first()
    if not utente or utente.role not in ["admin", "superadmin"]:
        raise HTTPException(403, detail="Accesso non autorizzato")

    TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
    TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")

    if not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN:
        raise HTTPException(500, detail="Credenziali Twilio mancanti")

    url = f"https://messaging.twilio.com/v1/Services/{TWILIO_ACCOUNT_SID}/Templates"

    response = requests.get(url, auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN))
    if response.status_code != 200:
        raise HTTPException(500, detail="Errore richiesta Twilio")

    data = response.json()
    inseriti = 0

    for t in data.get("templates", []):
        nome = t["name"]
        content_sid = t["sid"]
        descrizione = t.get("friendly_name") or "—"

        template_db = db.query(WhatsAppTemplate).filter_by(nome=nome).first()
        if template_db:
            template_db.content_sid = content_sid
            template_db.descrizione = descrizione
            template_db.attivo = True
        else:
            nuovo = WhatsAppTemplate(
                nome=nome,
                content_sid=content_sid,
                descrizione=descrizione,
                attivo=True
            )
            db.add(nuovo)
            inseriti += 1

    db.commit()

    return {
        "status": "ok",
        "sincronizzati": inseriti,
        "totali": len(data.get("templates", []))
    }

@router.post("/sessioni/crea/{cliente_id}")
def crea_sessione_whatsapp(
    cliente_id: int,
    db: Session = Depends(get_db),
    Authorize: AuthJWT = Depends()
):
    Authorize.jwt_required()

    cliente = db.query(Cliente).filter(Cliente.id == cliente_id).first()
    if not cliente or not cliente.telefono:
        raise HTTPException(status_code=404, detail="Cliente non trovato o telefono mancante")

    sessione = db.query(WhatsappSessione).filter_by(cliente_id=cliente.id).first()

    if not sessione:
        sessione = WhatsappSessione(
            cliente_id=cliente.id,
            numero=cliente.telefono.strip()
        )
        db.add(sessione)
        db.commit()
        db.refresh(sessione)

    return {"id": str(sessione.id)}

