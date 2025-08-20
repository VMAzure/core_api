from fastapi import APIRouter, Depends, HTTPException, Body
from pydantic import BaseModel, EmailStr
from typing import List, Optional, Union
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import User, SiteAdminSettings, NotificaType, Notifica
from app.utils.email import get_smtp_settings
from email.mime.text import MIMEText
from email.utils import formataddr
from app.utils.notifications import inserisci_notifica
from uuid import UUID

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
    tipo_codice: str  # ⬅️ lo imposta il frontend
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

        # 📝 Scrivi notifica in tabella
        inserisci_notifica(
            db=db,
            utente_id=user.id,
            cliente_id=None,
            tipo_codice=payload.tipo_codice,  # ⬅️ dinamico dal frontend
            messaggio=f"Richiesta da {payload.nome} {payload.cognome}: {payload.messaggio}"
        )


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
            # 📝 Scrivi notifica DB per ogni dealer
            inserisci_notifica(
                db=db,
                utente_id=dealer.id,
                cliente_id=None,
                tipo_codice="messaggio_admin",
                messaggio=payload.messaggio
            )

            server.quit()
            print(f"📨 Inviato a {dealer.email}")

        except Exception as e:
            print(f"❌ Errore invio a {dealer.email}: {e}")

    return { "success": True, "inviati": len(destinatari) }

class NotificaTypeCreateRequest(BaseModel):
    codice: str
    descrizione: str

class NotificaTypeResponse(BaseModel):
    id: int
    codice: str
    descrizione: str

    class Config:
        orm_mode = True

@router.get("/notifiche/tipi", response_model=List[NotificaTypeResponse])
def get_tipi_notifiche(db: Session = Depends(get_db)):
    tipi = db.query(NotificaType).order_by(NotificaType.id).all()
    return tipi

@router.post("/notifiche/tipi", response_model=NotificaTypeResponse)
def crea_tipo_notifica(
    payload: NotificaTypeCreateRequest = Body(...),
    db: Session = Depends(get_db)
):
    esistente = db.query(NotificaType).filter_by(codice=payload.codice).first()
    if esistente:
        raise HTTPException(status_code=400, detail="Codice già esistente")

    tipo = NotificaType(
        codice=payload.codice.strip(),
        descrizione=payload.descrizione.strip()
    )

    db.add(tipo)
    db.commit()
    db.refresh(tipo)
    return tipo


class NotificaItem(BaseModel):
    id: str
    tipo: str
    descrizione: str
    messaggio: str
    letta: bool
    data_creazione: str

    class Config:
        orm_mode = True


@router.get("/notifiche/mie", response_model=List[NotificaItem])
def get_notifiche_mie(
    letta: Optional[bool] = None,
    archiviata: bool = False,
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    Authorize.jwt_required()
    email = Authorize.get_jwt_subject()
    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(status_code=404, detail="Utente non trovato")

    query = db.query(Notifica).join(Notifica.tipo).filter(
        Notifica.utente_id == user.id,
        Notifica.archiviata == archiviata  # ✅ filtro default: false
    )

    if letta is not None:
        query = query.filter(Notifica.letta == letta)

    notifiche = query.order_by(Notifica.data_creazione.desc()).all()

    return [
        NotificaItem(
            id=str(n.id),
            tipo=n.tipo.codice,
            descrizione=n.tipo.descrizione,
            messaggio=n.messaggio,
            letta=n.letta,
            data_creazione=n.data_creazione.isoformat()
        ) for n in notifiche
    ]


@router.put("/notifiche/{notifica_id}/letta")
def segna_notifica_letta(
    notifica_id: UUID,
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    Authorize.jwt_required()
    email = Authorize.get_jwt_subject()
    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(status_code=404, detail="Utente non trovato")

    notifica = db.query(Notifica).filter(
        Notifica.id == notifica_id,
        Notifica.utente_id == user.id
    ).first()

    if not notifica:
        raise HTTPException(status_code=404, detail="Notifica non trovata o non tua")

    notifica.letta = True
    db.commit()

    return { "success": True, "message": "Notifica marcata come letta" }

from uuid import UUID

@router.put("/notifiche/{notifica_id}/archivia")
def archivia_notifica(
    notifica_id: UUID,
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    Authorize.jwt_required()
    email = Authorize.get_jwt_subject()
    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(status_code=404, detail="Utente non trovato")

    notifica = db.query(Notifica).filter(
        Notifica.id == notifica_id,
        Notifica.utente_id == user.id
    ).first()

    if not notifica:
        raise HTTPException(status_code=404, detail="Notifica non trovata o non tua")

    notifica.archiviata = True
    db.commit()

    return { "success": True, "message": "Notifica archiviata" }
