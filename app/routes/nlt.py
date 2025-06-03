from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException, Security, Query, Request

from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session, joinedload
from app.database import get_db
from app.models import NltPneumatici, NltAutoSostitutiva, NltService, NltDocumentiRichiesti, NltPreventivi, Cliente, User, NltPreventivi, NltPreventiviLinks, NltPreventiviTimeline, NltClientiPubblici
from pydantic import BaseModel, BaseSettings
from jose import jwt, JWTError  # ✅ Aggiunto import corretto per decodificare il token JWT
from fastapi_jwt_auth import AuthJWT
from fastapi.responses import RedirectResponse
from typing import List, Optional
from datetime import datetime, timedelta  # aggiunto timedelta
from app.utils.email import send_email
import uuid
from uuid import UUID
from app.utils.email import get_smtp_settings  # se vuoi usare direttamente la funzione già definita in email.py
import smtplib
from email.mime.text import MIMEText
from email.utils import formataddr
from app.routes.motornet import get_motornet_token  # Assicurati che questa funzione sia definita correttamente
from app.auth_helpers import (
    get_admin_id,
    get_dealer_id,
    is_admin_user,
    is_dealer_user
)


import httpx
import os


class Settings(BaseSettings):
    authjwt_secret_key: str = os.getenv("SECRET_KEY", "supersecretkey")  # ✅ Ora usa Pydantic

@AuthJWT.load_config
def get_config():
    return Settings()


router = APIRouter(
    prefix="/nlt",
    tags=["nlt"]
)

def get_current_user(Authorize: AuthJWT = Depends(), db: Session = Depends(get_db)):
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()

    user = db.query(User).filter(User.email == user_email).first()
    if not user:
        raise HTTPException(status_code=401, detail="Utente non trovato")
    return user



@router.get("/services")
async def get_nlt_services(db: Session = Depends(get_db)):
    services = db.query(NltService).filter(NltService.is_active == True).all()
    return {"services": services}

@router.get("/documenti-richiesti/{tipo_cliente}")
async def get_documenti_richiesti(tipo_cliente: str, db: Session = Depends(get_db)):
    documenti = db.query(NltDocumentiRichiesti)\
                  .filter(NltDocumentiRichiesti.tipo_cliente == tipo_cliente)\
                  .all()
    
    return {
        "tipo_cliente": tipo_cliente,
        "documenti": [doc.documento for doc in documenti]
    }

# 🔵 CONFIGURAZIONE SUPABASE
SUPABASE_URL = "https://vqfloobaovtdtcuflqeu.supabase.co"
SUPABASE_BUCKET = "nlt-preventivi"
SUPABASE_API_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InZxZmxvb2Jhb3Z0ZHRjdWZscWV1Iiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTczOTUzOTUzMCwiZXhwIjoyMDU1MTE1NTMwfQ.Lq-uIgXYZiBJK4ChfF_D7i5qYBDuxMfL2jY5GGKDuVk"

@router.post("/salva-preventivo")
async def salva_preventivo(
    file: UploadFile = File(...),
    cliente_id: int = Form(...),
    current_user: User = Depends(get_current_user),
    marca: str = Form(...),
    modello: str = Form(...),
    durata: int = Form(...),
    km_totali: int = Form(...),
    anticipo: float = Form(...),
    canone: float = Form(...),
    preventivo_assegnato_a: Optional[int] = Form(None),
    note: Optional[str] = Form(None),
    player: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    creato_da = current_user.id  # ✅ assegnato qui

    file_extension = file.filename.split(".")[-1]
    file_name = f"NLT_Offer_{uuid.uuid4()}.{file_extension}"
    file_path = f"{SUPABASE_BUCKET}/{file_name}"

    async with httpx.AsyncClient() as client:
        headers = {
            "Content-Type": file.content_type,
            "Authorization": f"Bearer {SUPABASE_API_KEY}"
        }
        response = await client.put(
            f"{SUPABASE_URL}/storage/v1/object/{file_path}",
            headers=headers,
            content=await file.read()
        )

    if response.status_code != 200:
        return {"success": False, "error": "Errore durante l'upload su Supabase."}

    file_url = f"{SUPABASE_URL}/storage/v1/object/public/{file_path}"

    nuovo_preventivo = NltPreventivi(
        cliente_id=cliente_id,
        file_url=file_url,
        creato_da=creato_da,
        marca=marca,
        modello=modello,
        durata=durata,
        km_totali=km_totali,
        anticipo=anticipo,
        canone=canone,
        visibile=1,
        preventivo_assegnato_a=preventivo_assegnato_a,
        note=note,
        player=player
    )

    db.add(nuovo_preventivo)
    db.commit()
    db.refresh(nuovo_preventivo)

    return {
        "success": True,
        "file_url": file_url,
        "preventivo_id": nuovo_preventivo.id,
        "dati": {
            "marca": nuovo_preventivo.marca,
            "modello": nuovo_preventivo.modello,
            "durata": nuovo_preventivo.durata,
            "km_totali": nuovo_preventivo.km_totali,
            "anticipo": nuovo_preventivo.anticipo,
            "canone": nuovo_preventivo.canone,
            "preventivo_assegnato_a": preventivo_assegnato_a,
            "note": note,
            "player": player
        }
    }


@router.get("/preventivi/{cliente_id}")
async def get_preventivi_cliente(
    cliente_id: int, 
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):

    # 🔍 Recupera il cliente
    cliente = db.query(Cliente).filter(Cliente.id == cliente_id).first()
    if not cliente:
        return {"success": False, "error": "Cliente non trovato"}

    # 🔍 Determina il nome del cliente
    nome_cliente = cliente.ragione_sociale if cliente.ragione_sociale else f"{cliente.nome} {cliente.cognome}".strip()

    # 🔹 Dealer: logica aggiornata
    if is_dealer_user(current_user):
        if current_user.shared_customers:
            dealer_id = get_dealer_id(current_user)
            team_ids = db.query(User.id).filter(
                (User.parent_id == dealer_id) |
                (User.id == dealer_id)
            ).subquery()


            preventivi = db.query(NltPreventivi).filter(
                NltPreventivi.creato_da.in_(team_ids),
                NltPreventivi.cliente_id == cliente_id
            ).all()
        else:
            preventivi = db.query(NltPreventivi).filter(
                NltPreventivi.creato_da == current_user.id,
                NltPreventivi.cliente_id == cliente_id
            ).all()

    # 🔹 Admin: vede i suoi e quelli dei suoi dealer
    elif current_user.role == "admin":
        dealer_ids = db.query(User.id).filter(User.parent_id == current_user.id).subquery()
        preventivi = db.query(NltPreventivi).filter(
            ((NltPreventivi.creato_da == current_user.id) | 
             (NltPreventivi.creato_da.in_(dealer_ids))) &
             (NltPreventivi.cliente_id == cliente_id)
        ).all()

    # 🔹 Superadmin: vede tutto per quel cliente
    else:
        preventivi = db.query(NltPreventivi).filter(NltPreventivi.cliente_id == cliente_id).all()

    return {
        "success": True,
        "cliente": nome_cliente,
        "preventivi": [
            {
                "id": p.id,
                "file_url": p.file_url,
                "creato_da": p.creato_da,
                "created_at": p.created_at,
                "marca": p.marca,
                "modello": p.modello,
                "durata": p.durata,
                "km_totali": p.km_totali,
                "anticipo": p.anticipo,
                "canone": p.canone
            }
            for p in preventivi
        ]
    }


@router.get("/preventivi")
async def get_miei_preventivi(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
    search: Optional[str] = Query(None)
):
    offset = (page - 1) * size

    if is_dealer_user(current_user):
        if current_user.shared_customers:
            team_ids = db.query(User.id).filter(
                (User.parent_id == current_user.parent_id) |
                (User.id == current_user.parent_id)
            ).all()

            team_ids_list = [id for (id,) in team_ids]

            query = db.query(NltPreventivi).join(Cliente).filter(
                (NltPreventivi.creato_da.in_(team_ids_list)) |
                (NltPreventivi.preventivo_assegnato_a == current_user.id),
                NltPreventivi.visibile == 1
            )
        else:
            query = db.query(NltPreventivi).join(Cliente).filter(
                (NltPreventivi.creato_da == current_user.id) |
                (NltPreventivi.preventivo_assegnato_a == current_user.id),
                NltPreventivi.visibile == 1
            )

    elif is_admin_user(current_user):
        admin_id = get_admin_id(current_user)
        dealer_ids = db.query(User.id).filter(User.parent_id == admin_id).all()
        dealer_ids_list = [id for (id,) in dealer_ids]
        dealer_ids_list.append(admin_id)


        query = db.query(NltPreventivi).join(Cliente).filter(
            NltPreventivi.creato_da.in_(dealer_ids_list),
            NltPreventivi.visibile == 1
        )

    else:  # superadmin
        query = db.query(NltPreventivi).join(Cliente).filter(NltPreventivi.visibile == 1)

    if search:
        search_term = f"%{search}%"
        query = query.filter(
            (Cliente.nome.ilike(search_term)) |
            (Cliente.cognome.ilike(search_term)) |
            (Cliente.ragione_sociale.ilike(search_term))
        )

    preventivi = query.order_by(NltPreventivi.created_at.desc()) \
                      .offset(offset) \
                      .limit(size) \
                      .all()

    risultati = []
    for p in preventivi:
        cliente = p.cliente

        email_evento = db.query(NltPreventiviTimeline).filter(
            NltPreventiviTimeline.preventivo_id == p.id,
            NltPreventiviTimeline.evento == "email_inviata"
        ).order_by(NltPreventiviTimeline.data_evento.desc()).first()

        email_inviata = bool(email_evento)
        data_email = email_evento.data_evento if email_evento else None


        if cliente.tipo_cliente == "Società":
            nome_cliente = cliente.ragione_sociale or "NN"
        else:
            nome_cliente = f"{cliente.nome or ''} {cliente.cognome or ''}".strip() or "NN"

        dealer = db.query(User).filter(User.id == p.creato_da).first()
        nome_dealer = f"{dealer.nome} {dealer.cognome}".strip() if dealer else "NN"
        # Dentro al ciclo che genera i risultati:
        dealer_assegnato = db.query(User).filter(User.id == p.preventivo_assegnato_a).first()
        nome_assegnato = f"{dealer_assegnato.nome} {dealer_assegnato.cognome}".strip() if dealer_assegnato else "Non assegnato"

        risultati.append({
            "id": p.id,
            "file_url": p.file_url,
            "creato_da": p.creato_da,
            "dealer_nome": nome_dealer,
            "created_at": p.created_at,
            "marca": p.marca,
            "modello": p.modello,
            "durata": p.durata,
            "km_totali": p.km_totali,
            "anticipo": p.anticipo,
            "canone": p.canone,
            "cliente": nome_cliente,
            "preventivo_assegnato_a": p.preventivo_assegnato_a,
            "preventivo_assegnato_nome": nome_assegnato,  # ✅ Aggiunto nome assegnato
            "note": p.note,
            "player": p.player,
            "email_inviata": email_inviata,
            "data_email": data_email

        })

    return {"preventivi": risultati}


@router.put("/nascondi-preventivo/{preventivo_id}")
async def nascondi_preventivo(preventivo_id: str, db: Session = Depends(get_db)):
    # 🔍 Cerca il preventivo nel database
    preventivo = db.query(NltPreventivi).filter(NltPreventivi.id == preventivo_id).first()

    if not preventivo:
        return {"success": False, "error": "Preventivo non trovato"}

    # 🔄 Imposta visibile = 0
    preventivo.visibile = 0
    db.commit()

    return {"success": True, "message": "Preventivo nascosto correttamente"}

@router.put("/aggiorna-preventivo/{preventivo_id}")
async def aggiorna_preventivo(
    preventivo_id: str,
    preventivo_assegnato_a: Optional[int] = Form(None),
    note: Optional[str] = Form(None),
    player: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    preventivo = db.query(NltPreventivi).filter(NltPreventivi.id == preventivo_id).first()
    if not preventivo:
        raise HTTPException(status_code=404, detail="Preventivo non trovato")

    # Aggiorna solo se fornito
    if preventivo_assegnato_a is not None:
        preventivo.preventivo_assegnato_a = preventivo_assegnato_a
    if note is not None:
        preventivo.note = note
    if player is not None:
        preventivo.player = player

    db.commit()
    db.refresh(preventivo)

    return {"success": True, "message": "Preventivo aggiornato con successo"}


@router.get("/preventivo-completo/{preventivo_id}")
async def get_preventivo_completo(preventivo_id: str, dealerId: Optional[int] = None, db: Session = Depends(get_db)):
    
    # ✅ PRIMA recupera il preventivo
    preventivo = db.query(NltPreventivi).filter(NltPreventivi.id == preventivo_id).first()
    if not preventivo:
        raise HTTPException(status_code=404, detail="Preventivo non trovato")

    # ✅ POI puoi usare preventivo
    dealer_id = dealerId or preventivo.preventivo_assegnato_a
    if not dealer_id:
        raise HTTPException(status_code=400, detail="Dealer non assegnato")

    dealer = db.query(User).filter(User.id == dealer_id).first()
    if not dealer:
        raise HTTPException(status_code=404, detail="Dealer non trovato")

    cliente = db.query(Cliente).filter(Cliente.id == preventivo.cliente_id).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente non trovato")

    admin = db.query(User).filter(User.id == preventivo.creato_da).first()
    if not admin:
        raise HTTPException(status_code=404, detail="Admin non trovato")

    # Recupera documenti richiesti
    import httpx

    async with httpx.AsyncClient() as client:
        res = await client.get(f"https://coreapi-production-ca29.up.railway.app/nlt/documenti-richiesti/{cliente.tipo_cliente}")
        documenti = res.json().get("documenti", []) if res.status_code == 200 else []

    return {
        "CustomerFirstName": cliente.nome,
        "CustomerLastName": cliente.cognome,
        "CustomerCompanyName": cliente.ragione_sociale,
        "TipoCliente": cliente.tipo_cliente,
        "CustomerEmail": cliente.email,   # <-- Aggiunto
        "ClienteId": preventivo.cliente_id,
        "NoteAuto": preventivo.note,
        "Player": preventivo.player,
        "DocumentiNecessari": documenti,

        "Auto": {
            "Marca": preventivo.marca,
            "Modello": preventivo.modello,
            "Versione": None,
            "Variante": None,
            "DescrizioneVersione": None,
            "Note": preventivo.note
        },

        "DatiEconomici": {
            "Durata": preventivo.durata,
            "KmTotali": preventivo.km_totali,
            "Anticipo": preventivo.anticipo,
            "Canone": preventivo.canone
        },

        "AdminInfo": {
            "Id": admin.id,
            "Email": admin.email,
            "FirstName": admin.nome,
            "LastName": admin.cognome,
            "CompanyName": admin.ragione_sociale,
            "VatNumber": admin.partita_iva,
            "Address": admin.indirizzo,
            "PostalCode": admin.cap,
            "City": admin.citta,
            "SDICode": admin.codice_sdi,
            "MobilePhone": admin.cellulare,
            "LogoUrl": admin.logo_url
        },

        "DealerInfo": {
            "Id": dealer.id,
            "Email": dealer.email,
            "FirstName": dealer.nome,
            "LastName": dealer.cognome,
            "CompanyName": dealer.ragione_sociale,
            "VatNumber": dealer.partita_iva,
            "Address": dealer.indirizzo,
            "PostalCode": dealer.cap,
            "City": dealer.citta,
            "SDICode": dealer.codice_sdi,
            "MobilePhone": dealer.cellulare,
            "LogoUrl": dealer.logo_url
        },

        "file_url": preventivo.file_url,
        "CarMainImageUrl": "",
        "CarImages": []
    }


def get_current_user_optional(Authorize: AuthJWT = Depends(), db: Session = Depends(get_db)):
    try:
        Authorize.jwt_required()
        user_email = Authorize.get_jwt_subject()
        user = db.query(User).filter(User.email == user_email).first()
        if not user:
            return None
        return user
    except:
        return None  # Utente non autenticato (chiamata interna server)

@router.post("/preventivi/{preventivo_id}/genera-link")
async def genera_link_preventivo(
    preventivo_id: str,
    current_user: Optional[User] = Depends(get_current_user_optional),
    db: Session = Depends(get_db)
):
    # Verifica preventivo
    preventivo = db.query(NltPreventivi).filter(NltPreventivi.id == preventivo_id).first()
    if not preventivo:
        raise HTTPException(status_code=404, detail="Preventivo non trovato")

    # genera token
    token = str(uuid.uuid4())

    nuovo_link = NltPreventiviLinks(
        token=token,
        preventivo_id=preventivo.id
    )

    db.add(nuovo_link)
    db.commit()

    url_download = f"https://coreapi-production-ca29.up.railway.app/nlt/preventivi/download/{token}"

    return {
        "token": token,
        "url_download": url_download
    }


@router.get("/preventivi/download/{token}")
async def download_preventivo(token: str, db: Session = Depends(get_db)):
    # Recupera il link
    link = db.query(NltPreventiviLinks).filter_by(token=token).first()
    
    if not link or link.data_scadenza < datetime.utcnow():
        raise HTTPException(status_code=404, detail="Link scaduto o invalido")

    # Recupera il preventivo associato
    preventivo = db.query(NltPreventivi).filter(NltPreventivi.id == link.preventivo_id).first()
    if not preventivo:
        raise HTTPException(status_code=404, detail="Preventivo non trovato")

    # Determina l'utente responsabile (assegnato o creatore)
    responsabile_id = preventivo.preventivo_assegnato_a or preventivo.creato_da

    # Aggiorna link come usato
    link.usato = True

    # Registra evento nella timeline
    evento = NltPreventiviTimeline(
        preventivo_id=link.preventivo_id,
        evento="scaricato",
        descrizione=f"Preventivo scaricato tramite link (token={token})",
        utente_id=responsabile_id,
        data_evento=datetime.utcnow()
    )

    db.add(evento)
    db.commit()

    # Redirect al file
    return RedirectResponse(preventivo.file_url)



@router.post("/preventivi/{preventivo_id}/invia-mail")
async def invia_mail_preventivo(
    preventivo_id: UUID,
    body: dict,
    current_user: Optional[User] = Depends(get_current_user_optional),
    db: Session = Depends(get_db)
):

    preventivo = db.query(NltPreventivi).filter(NltPreventivi.id == preventivo_id).first()
    if not preventivo:
        raise HTTPException(status_code=404, detail="Preventivo non trovato")

    cliente = db.query(Cliente).filter(Cliente.id == preventivo.cliente_id).first()
    if not cliente or not cliente.email:
        raise HTTPException(status_code=404, detail="Cliente o email non trovati")

    email_destinatario = cliente.email

    # recupera SMTP (admin)
    if current_user:
        user_id = current_user.parent_id or current_user.id
    else:
        creatore = db.query(User).filter(User.id == preventivo.creato_da).first()
        if not creatore:
            raise HTTPException(status_code=404, detail="Creatore preventivo non trovato")
        user_id = creatore.parent_id or creatore.id

    smtp_settings = get_smtp_settings(user_id, db)

    if not smtp_settings:
        raise HTTPException(status_code=500, detail="SMTP non configurato")

    # Componi il messaggio
    html_body = body.get("html_body", f"Clicca per scaricare il preventivo: {body['url_download']}")

    msg = MIMEText(html_body, "html", "utf-8")
    msg["Subject"] = f"Preventivo {preventivo.marca} {preventivo.modello}"
    msg["From"] = formataddr((smtp_settings.smtp_alias or "Preventivo Noleggio Lungo Termine", smtp_settings.smtp_user))
    msg["To"] = email_destinatario
    dealer = db.query(User).filter(User.id == preventivo.preventivo_assegnato_a).first()
    if dealer and dealer.email:
        msg["Bcc"] = dealer.email

    # Invia mail
    try:
        if smtp_settings.use_ssl:
            server = smtplib.SMTP_SSL(smtp_settings.smtp_host, smtp_settings.smtp_port)
        else:
            server = smtplib.SMTP(smtp_settings.smtp_host, smtp_settings.smtp_port)
            server.starttls()

        server.login(smtp_settings.smtp_user, smtp_settings.smtp_password)
        server.send_message(msg)
        server.quit()
        print("✅ Email inviata correttamente a", email_destinatario)

        # Registra evento in timeline
        responsabile_id = preventivo.preventivo_assegnato_a or preventivo.creato_da

        evento = NltPreventiviTimeline(
            preventivo_id=preventivo.id,
            evento="email_inviata",
            descrizione=f"Email inviata a {cliente.email}",
            data_evento=datetime.utcnow(),
            utente_id=responsabile_id
        )

        db.add(evento)
        db.commit()

    except smtplib.SMTPException as smtp_err:
        print("❌ Errore SMTP:", smtp_err)
        raise HTTPException(status_code=500, detail=f"Errore SMTP: {smtp_err}")

    except Exception as e:
        print("❌ Errore generico invio email:", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/preventivi/cliente-token/{token}")
def recupera_preventivo_da_token_cliente(token: str, db: Session = Depends(get_db)):
    cliente_pubblico = db.query(NltClientiPubblici).filter_by(token=token).first()

    if not cliente_pubblico:
        raise HTTPException(status_code=404, detail="Cliente pubblico non trovato")

    cliente_definitivo = db.query(Cliente).filter_by(email=cliente_pubblico.email).first()

    if not cliente_definitivo:
        raise HTTPException(status_code=404, detail="Cliente definitivo non trovato")

    preventivo = db.query(NltPreventivi)\
        .filter_by(cliente_id=cliente_definitivo.id)\
        .order_by(NltPreventivi.created_at.desc())\
        .first()

    if not preventivo:
        return {"preventivo_id": None}

    return {"preventivo_id": str(preventivo.id)}

@router.get("/pneumatici/{codice_motornet}", tags=["Servizi Extra"])
async def get_costo_pneumatici_da_motornet(
    codice_motornet: str,
    request: Request,
    db: Session = Depends(get_db)
):
    import re
    import httpx


    # ⏬ Prendi il token già presente (utente loggato)
    jwt_token = request.headers.get("Authorization")
    if not jwt_token:
        raise HTTPException(status_code=401, detail="Token mancante")

    headers = {"Authorization": jwt_token}

    url = f"https://coreapi-production-ca29.up.railway.app/api/nuovo/motornet/dettagli/{codice_motornet}"

    async with httpx.AsyncClient() as client:
        res = await client.get(url, headers=headers)

    if res.status_code != 200:
        raise HTTPException(status_code=res.status_code, detail="Errore nel recupero dati motornet")

    data = res.json()
    modello = data.get("modello", {})

    anteriori = modello.get("pneumatici_anteriori", "")
    posteriori = modello.get("pneumatici_posteriori", "")

    diametri = []
    for misura in [anteriori, posteriori]:
        match = re.search(r"R(\d{2})", misura)
        if match:
            diametri.append(int(match.group(1)))

    if not diametri:
        raise HTTPException(status_code=422, detail="Diametro non trovato nei dati ricevuti")

    diametro_maggiore = max(diametri)

    record = db.query(NltPneumatici).filter(NltPneumatici.diametro == diametro_maggiore).first()
    if not record:
        raise HTTPException(status_code=404, detail=f"Nessun costo trovato per cerchi R{diametro_maggiore}")

    return {
        "costo_treno": float(record.costo_treno)
    }


@router.get("/autosostitutiva/{segmento}")
def get_costo_autosostitutiva(segmento: str, db: Session = Depends(get_db)):
    record = db.query(NltAutoSostitutiva).filter(NltAutoSostitutiva.segmento == segmento.upper()).first()
    if not record:
        raise HTTPException(status_code=404, detail="Segmento non trovato")
    return {"segmento": record.segmento, "costo_mensile": float(record.costo_mensile)}
