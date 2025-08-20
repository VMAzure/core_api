from fastapi import APIRouter, Depends, HTTPException, Body
from pydantic import BaseModel, EmailStr
from typing import List, Optional, Union
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import User, SiteAdminSettings
from app.utils.email import get_smtp_settings
from email.mime.text import MIMEText
from email.utils import formataddr
from app.auth_helpers import is_admin_user, get_admin_id
from fastapi_jwt_auth import AuthJWT
import smtplib

router = APIRouter()


# --- 1. Notifica da lead generico (pubblico) ---
class NotificaDealerRequest(BaseModel):
    nome: str
    cognome: str
    telefono: str
    email: EmailStr
    messaggio: str
    tipo_cliente: Optional[str] = None
    ragione_sociale: Optional[str] = None
    dealer_slug: str


@router.post("/notifiche/dealer")
def invia_notifica_dealer(
    payload: NotificaDealerRequest = Body(...),
    db: Session = Depends(get_db)
):
    # Trova impostazioni dealer per risalire all'admin
    settings = db.query(SiteAdminSettings).filter_by(slug=payload.dealer_slug).first()
    if not settings:
        raise HTTPException(status_code=404, detail="Dealer non trovato")

    owner_id = settings.admin_id or settings.dealer_id
    user = db.query(User).filter(User.id == owner_id).first()

    if not user or not user.email:
        raise HTTPException(status_code=404, detail="Email destinatario non trovata")

    smtp = get_smtp_settings(owner_id, db)
    if not smtp:
        raise HTTPException(status_code=500, detail="SMTP non configurato")

    # Componi HTML email
    html = f"""
    <h3>📩 Nuova richiesta informazioni</h3>
    <p><strong>Nome:</strong> {payload.nome} {payload.cognome}<br>
    <strong>Email:</strong> {payload.email}<br>
    <strong>Telefono:</strong> {payload.telefono}<br>
    """

    if payload.ragione_sociale:
        html += f"<strong>Ragione sociale:</strong> {payload.ragione_sociale}<br>"

    if payload.tipo_cliente:
        html += f"<strong>Tipo cliente:</strong> {payload.tipo_cliente}<br>"

    html += f"</p><p><strong>Messaggio:</strong><br>{payload.messaggio}</p>"

    msg = MIMEText(html, "html", "utf-8")
    msg["Subject"] = f"Richiesta da {payload.nome} {payload.cognome}"
    msg["From"] = formataddr((smtp.smtp_alias or "Lead Noleggio", smtp.smtp_user))
    msg["To"] = user.email

    try:
        if smtp.use_ssl:
            server = smtplib.SMTP_SSL(smtp.smtp_host, smtp.smtp_port)
        else:
            server = smtplib.SMTP(smtp.smtp_host, smtp.smtp_port)
            server.starttls()

        server.login(smtp.smtp_user, smtp.smtp_password)
        server.send_message(msg)
        server.quit()

        return { "success": True, "message": "Notifica inviata" }

    except Exception as e:
        print("❌ Errore invio mail:", e)
        raise HTTPException(status_code=500, detail="Errore invio email")


# --- 2. Notifica broadcast da admin ---
class AdminNotificaRequest(BaseModel):
    oggetto: str
    messaggio: str
    destinatari: Union[str, List[int]]  # "all" o lista ID


@router.post("/admin/notifiche/dealer")
def invia_notifica_broadcast(
    payload: AdminNotificaRequest = Body(...),
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()
    admin = db.query(User).filter(User.email == user_email).first()

    if not admin or not is_admin_user(admin):
        raise HTTPException(status_code=403, detail="Solo admin autorizzati")

    smtp = get_smtp_settings(get_admin_id(admin), db)
    if not smtp:
        raise HTTPException(status_code=500, detail="SMTP non configurato per l'admin")

    # Risolvi destinatari
    if payload.destinatari == "all":
        destinatari = db.query(User).filter(User.role == "dealer").all()
    elif isinstance(payload.destinatari, list):
        destinatari = db.query(User).filter(User.id.in_(payload.destinatari), User.role == "dealer").all()
    else:
        raise HTTPException(status_code=400, detail="Destinatari non validi")

    if not destinatari:
        raise HTTPException(status_code=404, detail="Nessun dealer trovato")

    # Invio email a ciascun destinatario
    for dealer in destinatari:
        msg = MIMEText(payload.messaggio, "html", "utf-8")
        msg["Subject"] = payload.oggetto
        msg["From"] = formataddr((smtp.smtp_alias or "Comunicazioni Admin", smtp.smtp_user))
        msg["To"] = dealer.email

        try:
            if smtp.use_ssl:
                server = smtplib.SMTP_SSL(smtp.smtp_host, smtp.smtp_port)
            else:
                server = smtplib.SMTP(smtp.smtp_host, smtp.smtp_port)
                server.starttls()

            server.login(smtp.smtp_user, smtp.smtp_password)
            server.send_message(msg)
            server.quit()
            print(f"📨 Inviato a {dealer.email}")

        except Exception as e:
            print(f"❌ Errore invio a {dealer.email}: {e}")

    return { "success": True, "inviati": len(destinatari) }
