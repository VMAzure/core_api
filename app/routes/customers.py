from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from app.database import get_db, engine  # sostituisci con import corretto

from app.models import User, Cliente, ClienteModifica, NltPreventivi, NltPreventiviLinks, NltClientiPubblici, SiteAdminSettings
from fastapi_jwt_auth import AuthJWT
from typing import List, Optional
from app.schemas import ClienteResponse, ClienteCreateRequest, NltClientiPubbliciCreate, NltClientiPubbliciResponse
from fastapi import Query, Body, BackgroundTasks

from pydantic import BaseModel
import uuid
from app.utils.email import send_email
from sqlalchemy import or_
from app.models import NltOfferte, NltService, NltDocumentiRichiesti

import os

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_BUCKET = os.getenv("SUPABASE_BUCKET")
SUPABASE_API_KEY = os.getenv("SUPABASE_API_KEY")

router = APIRouter()
from app.auth_helpers import (
    get_admin_id,
    get_dealer_id,
    is_admin_user,
    is_dealer_user
)


@router.get("/clienti", response_model=List[ClienteResponse])
def get_clienti(
    dealer_id: Optional[int] = Query(None),
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()

    user = db.query(User).filter(User.email == user_email).first()
    if not user:
        raise HTTPException(status_code=404, detail="Utente non trovato")

    # 👇 Se viene passato un dealer_id in query → restituisci SOLO i clienti di quel dealer
    if dealer_id:
        clienti = db.query(Cliente).filter(Cliente.dealer_id == dealer_id).all()
        return clienti

    # Altrimenti si comporta normalmente
    if user.role == "superadmin":
        clienti = db.query(Cliente).all()
    elif is_admin_user(user):
        admin_id = get_admin_id(user)
        clienti = db.query(Cliente).filter(Cliente.admin_id == admin_id).all()
    elif is_dealer_user(user):
        dealer_id = get_dealer_id(user)
        clienti = db.query(Cliente).filter(Cliente.dealer_id == dealer_id).all()
    else:
        raise HTTPException(status_code=403, detail="Ruolo non autorizzato")

    return clienti



# Richiesta per verifica cliente
class ClienteCheckRequest(BaseModel):
    tipo_cliente: str
    codice_fiscale: Optional[str] = None
    partita_iva: Optional[str] = None



# Endpoint verifica esistenza cliente
@router.post("/clienti/check-exists")
def check_cliente_exists(
    check: ClienteCheckRequest,
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()

    user = db.query(User).filter(User.email == user_email).first()
    if not user:
        raise HTTPException(status_code=404, detail="Utente non trovato")

    # Se l'utente è dealer, cerca fra tutti i clienti dell'admin associato
    admin_id = get_admin_id(user)
    query = db.query(Cliente).filter(Cliente.admin_id == admin_id)

    # Logica di controllo aggiornata
    if check.tipo_cliente == "Privato":
        if not check.codice_fiscale:
            raise HTTPException(status_code=400, detail="Codice Fiscale obbligatorio per Privato")

        cliente_esistente = query.filter(
            Cliente.codice_fiscale == check.codice_fiscale
        ).first()

    elif check.tipo_cliente in ["Società", "Professionista"]:
        if not check.partita_iva:
            raise HTTPException(status_code=400, detail="Partita IVA obbligatoria per Società e Professionista")

        cliente_esistente = query.filter(
            Cliente.partita_iva == check.partita_iva
        ).first()
    else:
        raise HTTPException(status_code=400, detail="Tipo cliente non valido")

    if cliente_esistente:
        return {
            "exists": True,
            "cliente": {
                "id": cliente_esistente.id,
                "nome": cliente_esistente.nome,
                "cognome": cliente_esistente.cognome,
                "codice_fiscale": cliente_esistente.codice_fiscale,
                "partita_iva": cliente_esistente.partita_iva
            },
            "message": "Cliente già assegnato sotto il tuo Admin"
        }

    return {
        "exists": False,
        "message": "Cliente disponibile"
    }


# Endpoint creazione nuovo cliente
@router.post("/clienti", response_model=ClienteResponse)
def crea_cliente(
    cliente: ClienteCreateRequest,
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()

    user = db.query(User).filter(User.email == user_email).first()
    if not user:
        raise HTTPException(status_code=404, detail="Utente non trovato")

    admin_id = get_admin_id(user)
    dealer_id = get_dealer_id(user)

    # 👇 Se il payload include un dealer_id, usalo (es. da parte di un admin)
    if hasattr(cliente, "dealer_id") and cliente.dealer_id:
        dealer_id = cliente.dealer_id

    # Verifica duplicati cliente sotto lo stesso Admin/Dealer
    query = db.query(Cliente).filter(Cliente.admin_id == admin_id)

    if dealer_id:
        query = query.filter(Cliente.dealer_id == dealer_id)

    if cliente.tipo_cliente == "Privato":
        if not cliente.codice_fiscale:
            raise HTTPException(status_code=400, detail="Codice Fiscale obbligatorio per Privato")
        query = query.filter(Cliente.codice_fiscale == cliente.codice_fiscale)

    else:
        if not cliente.partita_iva:
            raise HTTPException(status_code=400, detail="Partita IVA obbligatoria per Società e Professionista")
        query = query.filter(Cliente.partita_iva == cliente.partita_iva)

    if query.first():
        raise HTTPException(status_code=400, detail="Cliente già assegnato sotto questo Admin/Dealer")

    # Imposta ragione_sociale a None se il cliente è privato
    if cliente.tipo_cliente == "Privato":
        cliente.ragione_sociale = None

    # Creazione cliente
    nuovo_cliente = Cliente(
        admin_id=admin_id,
        dealer_id=dealer_id,
        tipo_cliente=cliente.tipo_cliente,
        nome=cliente.nome,
        cognome=cliente.cognome,
        ragione_sociale=cliente.ragione_sociale,
        codice_fiscale=cliente.codice_fiscale,
        partita_iva=cliente.partita_iva,
        indirizzo=cliente.indirizzo,
        telefono=cliente.telefono,
        email=cliente.email,
        iban=cliente.iban,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
    )

    db.add(nuovo_cliente)

    try:
        db.commit()
        db.refresh(nuovo_cliente)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail="Errore inserimento cliente, possibile duplicato o dati errati.")

    return nuovo_cliente

class RichiestaModificaCliente(BaseModel):
    campo_modificato: str
    valore_nuovo: str
    messaggio: Optional[str] = None

@router.post("/clienti/{cliente_id}/richiedi-modifica")
def richiedi_modifica_cliente(
    cliente_id: int,
    richiesta: RichiestaModificaCliente,
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()

    user = db.query(User).filter(User.email == user_email).first()
    if not user or not is_dealer_user(user):
        raise HTTPException(status_code=403, detail="Accesso non autorizzato")

    cliente = db.query(Cliente).filter(
        Cliente.id == cliente_id,
        Cliente.dealer_id == get_dealer_id(user)
    ).first()

    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente non trovato")

    modifica = ClienteModifica(
        cliente_id=cliente.id,
        richiesto_da=user.id,
        campo_modificato=richiesta.campo_modificato,
        valore_vecchio=getattr(cliente, richiesta.campo_modificato),
        valore_nuovo=richiesta.valore_nuovo,
        messaggio=richiesta.messaggio,
        stato="In attesa"
    )

    db.add(modifica)
    db.commit()
    db.refresh(modifica)

    return {"msg": "Richiesta modifica inviata correttamente", "id_richiesta": modifica.id}

@router.put("/clienti/{cliente_id}/modifica")
def modifica_cliente(
    cliente_id: int,
    dati_cliente: ClienteCreateRequest,
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()

    user = db.query(User).filter(User.email == user_email).first()
    if not user or not is_admin_user(user):
        raise HTTPException(status_code=403, detail="Accesso non autorizzato")

    admin_id = get_admin_id(user)

    cliente = db.query(Cliente).filter(
        Cliente.id == cliente_id,
        Cliente.admin_id == admin_id
    ).first()

    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente non trovato o non appartenente a questo admin")

    for key, value in dati_cliente.dict().items():
        setattr(cliente, key, value)

    cliente.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(cliente)

    return {"msg": "Cliente modificato correttamente", "cliente": cliente}

from app.models import ClienteConsenso
from app.schemas import ClienteConsensoRequest, ClienteConsensoResponse

@router.post("/clienti/{cliente_id}/consensi", response_model=ClienteConsensoResponse)
def registra_consenso_cliente(
    cliente_id: int,
    consenso: ClienteConsensoRequest,
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()

    user = db.query(User).filter(User.email == user_email).first()
    if not user:
        raise HTTPException(status_code=404, detail="Utente non trovato")

    cliente = db.query(Cliente).filter(Cliente.id == cliente_id).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente non trovato")

    nuovo_consenso = ClienteConsenso(
        cliente_id=cliente_id,
        privacy=consenso.privacy,
        newsletter=consenso.newsletter,
        marketing=consenso.marketing,
        ip=consenso.ip,
        note=consenso.note,
        attivo=consenso.attivo, # ✅ aggiunto campo attivo
        data_consenso=datetime.utcnow()
    )

    db.add(nuovo_consenso)
    db.commit()
    db.refresh(nuovo_consenso)

    return nuovo_consenso

@router.get("/clienti/{cliente_id}/consensi", response_model=List[ClienteConsensoResponse])
def get_consensi_cliente(
    cliente_id: int,
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()

    user = db.query(User).filter(User.email == user_email).first()
    if not user:
        raise HTTPException(status_code=404, detail="Utente non trovato")

    cliente = db.query(Cliente).filter(Cliente.id == cliente_id).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente non trovato")

    consensi = db.query(ClienteConsenso).filter(ClienteConsenso.cliente_id == cliente_id).all()

    return consensi

class ClienteConsensoUpdateRequest(BaseModel):
    privacy: Optional[bool]
    newsletter: Optional[bool]
    marketing: Optional[bool]
    attivo: Optional[bool]
    note: Optional[str]

@router.put("/clienti/consensi/{consenso_id}", response_model=ClienteConsensoResponse)
def aggiorna_consenso_cliente(
    consenso_id: uuid.UUID,
    consenso: ClienteConsensoUpdateRequest,
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()

    user = db.query(User).filter(User.email == user_email).first()
    if not user:
        raise HTTPException(status_code=404, detail="Utente non trovato")

    consenso_db = db.query(ClienteConsenso).filter(ClienteConsenso.id == consenso_id).first()
    if not consenso_db:
        raise HTTPException(status_code=404, detail="Consenso non trovato")

    # ✅ Aggiorna i campi forniti
    for key, value in consenso.dict(exclude_unset=True).items():
        setattr(consenso_db, key, value)

    consenso_db.data_consenso = datetime.utcnow()  # aggiorna data modifica consenso

    db.commit()
    db.refresh(consenso_db)

    return consenso_db

@router.delete("/clienti/consensi/{consenso_id}")
def revoca_consenso_cliente(
    consenso_id: uuid.UUID,
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()

    user = db.query(User).filter(User.email == user_email).first()
    if not user:
        raise HTTPException(status_code=404, detail="Utente non trovato")

    consenso_db = db.query(ClienteConsenso).filter(ClienteConsenso.id == consenso_id).first()
    if not consenso_db:
        raise HTTPException(status_code=404, detail="Consenso non trovato")

    consenso_db.attivo = False
    consenso_db.data_consenso = datetime.utcnow()  # aggiorna data modifica consenso

    db.commit()

    return {"detail": "Consenso revocato correttamente"}


@router.post("/public/clienti/{cliente_id}/consensi")
def registra_consenso_pubblico(
    cliente_id: int,
    token: str = Query(...),
    consensi: ClienteConsensoRequest = ...,
    db: Session = Depends(get_db)
):
    # Verifica validità token
    link = db.query(NltPreventiviLinks).filter_by(token=token).first()
    if not link or link.data_scadenza < datetime.utcnow():
        raise HTTPException(status_code=403, detail="Link non valido o scaduto")

    # Verifica che il preventivo collegato appartenga al cliente
    preventivo = db.query(NltPreventivi).filter_by(id=link.preventivo_id, cliente_id=cliente_id).first()
    if not preventivo:
        raise HTTPException(status_code=404, detail="Preventivo non trovato per questo cliente")

    nuovo_consenso = ClienteConsenso(
        cliente_id=cliente_id,
        privacy=consensi.privacy,
        newsletter=consensi.newsletter,
        marketing=consensi.marketing,
        ip=consensi.ip,
        note=consensi.note,
        attivo=True,
        data_consenso=datetime.utcnow()
    )

    db.add(nuovo_consenso)
    db.commit()
    db.refresh(nuovo_consenso)

    return {"success": True, "msg": "Consenso registrato"}


@router.post("/public/clienti", response_model=NltClientiPubbliciResponse)
def crea_cliente_pubblico(
    payload: NltClientiPubbliciCreate,
    db: Session = Depends(get_db)
):
    # Recupera il dealer tramite slug
    dealer = db.query(User).join(
        SiteAdminSettings,
        ((SiteAdminSettings.dealer_id == User.id) | ((SiteAdminSettings.dealer_id == None) & (SiteAdminSettings.admin_id == User.id)))
    ).filter(
        SiteAdminSettings.slug == payload.dealer_slug
    ).first()

    if not dealer:
        raise HTTPException(status_code=404, detail="Dealer non trovato.")

    # Controlla se il cliente è già censito
    cliente_esistente = db.query(Cliente).filter(Cliente.email.ilike(payload.email)).first()

    # Genera token e scadenza
    token = str(uuid.uuid4())
    data_creazione = datetime.utcnow()
    data_scadenza = data_creazione + timedelta(days=7)

    # Determina stato cliente
    if cliente_esistente:
        if cliente_esistente.dealer_id == dealer.id:
            stato_cliente = "cliente_stesso_dealer"
        else:
            stato_cliente = "cliente_altro_dealer"
    else:
        stato_cliente = "nuovo_cliente"

    # Salva nella tabella NltClientiPubblici
    nuovo_cliente_pubblico = NltClientiPubblici(
        email=payload.email,
        dealer_slug=payload.dealer_slug,
        token=token,
        data_creazione=data_creazione,
        data_scadenza=data_scadenza,
        confermato=False,
        slug_offerta=str(payload.slug_offerta) if payload.slug_offerta else None,
        anticipo=float(payload.anticipo) if payload.anticipo is not None else None,
        canone=float(payload.canone) if payload.canone is not None else None,
        durata=int(payload.durata) if payload.durata is not None else None,
        km=int(payload.km) if payload.km is not None else None
    )


    db.add(nuovo_cliente_pubblico)
    db.commit()
    db.refresh(nuovo_cliente_pubblico)

    # Gestione email differenziata
    admin_id = dealer.parent_id or dealer.id
    subject = "Completa la tua richiesta di preventivo"

    base_url_frontend = "https://corewebapp-azcore.up.railway.app/AZURELease/html"

    if stato_cliente == "nuovo_cliente":
        url = f"{base_url_frontend}/conferma-dati-cliente.html?token={token}"
        body = f"""
        <p>Gentile cliente, clicca per completare i tuoi dati:</p>
        <p><a href="{url}">{url}</a></p>
        """
    elif stato_cliente == "cliente_stesso_dealer":
        url = f"{base_url_frontend}/scarica-preventivo.html?token={token}"
        body = f"""
        <p>Gentile cliente, il tuo preventivo è già pronto:</p>
        <p><a href="{url}">Scarica preventivo</a></p>
        """
    else:  # cliente_altro_dealer
        url = f"{base_url_frontend}/scelta-dealer.html?token={token}"
        body = f"""
        <p>Gentile cliente, risultano i tuoi dati già registrati presso un altro dealer.</p>
        <p>Clicca per scegliere da chi vuoi ricevere il preventivo:</p>
        <p><a href="{url}">{url}</a></p>
        """

    # try:
    #     send_email(admin_id, payload.email, subject, body)
    # except Exception as e:
    #     db.rollback()
    #     raise HTTPException(status_code=500, detail=f"Errore invio email: {str(e)}")


    return NltClientiPubbliciResponse(
        id=nuovo_cliente_pubblico.id,
        email=payload.email,
        dealer_slug=payload.dealer_slug,
        token=token,
        data_creazione=data_creazione,
        data_scadenza=data_scadenza,
        confermato=False,
        stato=stato_cliente
    )

@router.get("/public/clienti/conferma/{token}", response_model=NltClientiPubbliciResponse)
def conferma_cliente_pubblico(token: str, db: Session = Depends(get_db)):
    cliente_pubblico = db.query(NltClientiPubblici).filter(
        NltClientiPubblici.token == token,
        NltClientiPubblici.data_scadenza >= datetime.utcnow()
    ).first()

    if not cliente_pubblico:
        raise HTTPException(status_code=404, detail="Token non valido o scaduto")

    cliente_esistente = db.query(Cliente).filter(Cliente.email.ilike(cliente_pubblico.email)).first()

    dealer_richiesto = db.query(User).join(
        SiteAdminSettings,
        ((SiteAdminSettings.dealer_id == User.id) | ((SiteAdminSettings.dealer_id == None) & (SiteAdminSettings.admin_id == User.id)))
    ).filter(SiteAdminSettings.slug == cliente_pubblico.dealer_slug).first()

    stato = "nuovo_cliente"
    if cliente_esistente:
        if cliente_esistente.dealer_id == dealer_richiesto.id:
            stato = "cliente_stesso_dealer"
        else:
            stato = "cliente_altro_dealer"

    return NltClientiPubbliciResponse(
        id=cliente_pubblico.id,
        email=cliente_pubblico.email,
        dealer_slug=cliente_pubblico.dealer_slug,
        cliente_id=cliente_pubblico.cliente_id,
        token=token,
        data_creazione=cliente_pubblico.data_creazione,
        data_scadenza=cliente_pubblico.data_scadenza,
        confermato=cliente_pubblico.confermato,
        stato=stato,
        slug_offerta=cliente_pubblico.slug_offerta,
        anticipo=cliente_pubblico.anticipo,
        canone=cliente_pubblico.canone,
        durata=cliente_pubblico.durata,
        km=cliente_pubblico.km
    )

@router.post("/public/clienti", response_model=NltClientiPubbliciResponse)
def crea_cliente_pubblico(payload: NltClientiPubbliciCreate, db: Session = Depends(get_db)):
    dealer = db.query(User).join(
        SiteAdminSettings,
        ((SiteAdminSettings.dealer_id == User.id) | ((SiteAdminSettings.dealer_id == None) & (SiteAdminSettings.admin_id == User.id)))
    ).filter(SiteAdminSettings.slug == payload.dealer_slug).first()

    if not dealer:
        raise HTTPException(status_code=404, detail="Dealer non trovato.")

    token = str(uuid.uuid4())
    data_creazione = datetime.utcnow()
    data_scadenza = data_creazione + timedelta(days=7)

    cliente_pubblico = NltClientiPubblici(
        email=payload.email,
        dealer_slug=payload.dealer_slug,
        token=token,
        data_creazione=data_creazione,
        data_scadenza=data_scadenza,
        confermato=False,
        slug_offerta=payload.slug_offerta,
        anticipo=payload.anticipo,
        canone=payload.canone,
        durata=payload.durata,
        km=payload.km
    )

    db.add(cliente_pubblico)
    db.commit()
    db.refresh(cliente_pubblico)

    return NltClientiPubbliciResponse(
        id=cliente_pubblico.id,
        email=payload.email,
        dealer_slug=payload.dealer_slug,
        stato="nuovo_cliente",
        token=token,
        cliente_id=None,
        data_creazione=data_creazione,
        data_scadenza=data_scadenza,
        confermato=False,
        slug_offerta=payload.slug_offerta,
        anticipo=payload.anticipo,
        canone=payload.canone,
        durata=payload.durata,
        km=payload.km
    )

@router.post("/public/clienti/switch-anagrafica")
def switch_cliente_anagrafica(
    cliente_id: int,
    nuovo_dealer_slug: str,
    nuova_email: str,
    db: Session = Depends(get_db)
):
    cliente = db.query(Cliente).filter(Cliente.id == cliente_id).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente non trovato")

    nuovo_dealer = db.query(User).join(SiteAdminSettings).filter(
        SiteAdminSettings.slug == nuovo_dealer_slug
    ).first()

    if not nuovo_dealer:
        raise HTTPException(status_code=404, detail="Dealer non trovato")

    vecchio_dealer = cliente.dealer or cliente.admin
    vecchio_nome = vecchio_dealer.ragione_sociale or f"{vecchio_dealer.nome} {vecchio_dealer.cognome}"

    cliente.admin_id = nuovo_dealer.parent_id or nuovo_dealer.id
    cliente.dealer_id = None if nuovo_dealer.role == "admin" else nuovo_dealer.id
    cliente.email = nuova_email
    cliente.updated_at = datetime.utcnow()

    db.commit()

    # Invia mail al vecchio dealer per avvisarlo
    send_email(
        vecchio_dealer.id, vecchio_dealer.email,
        "Notifica cambio assegnazione cliente",
        f"Il cliente {cliente.nome} {cliente.cognome} ha trasferito la sua anagrafica al nuovo dealer: {nuovo_dealer_slug}"
    )

    # Invia preventivo al cliente con nuovo dealer
    send_email(
        cliente.admin_id, cliente.email,
        "Preventivo aggiornato con nuovo dealer",
        "Ecco il tuo preventivo aggiornato (link o allegato)."
    )

    return {"status": "cliente_switch_avvenuto", "cliente_id": cliente.id, "nuovo_dealer": nuovo_dealer_slug}


@router.post("/public/clienti/completa-registrazione")
def completa_registrazione_cliente_pubblico(
    token: str = Query(...), # <--- dalla query
    cliente: ClienteCreateRequest = Body(...),
    db: Session = Depends(get_db),
    background_tasks: BackgroundTasks = BackgroundTasks()
):

    # verifica token
    cliente_pubblico = db.query(NltClientiPubblici).filter(
        NltClientiPubblici.token == token,
        NltClientiPubblici.data_scadenza >= datetime.utcnow(),
        NltClientiPubblici.confermato == False
    ).first()

    if not cliente_pubblico:
        raise HTTPException(status_code=404, detail="Token non valido o scaduto")

    dealer = db.query(User).join(
        SiteAdminSettings,
        ((SiteAdminSettings.dealer_id == User.id) | ((SiteAdminSettings.dealer_id == None) & (SiteAdminSettings.admin_id == User.id)))
    ).filter(SiteAdminSettings.slug == cliente_pubblico.dealer_slug).first()

    if not dealer:
        raise HTTPException(status_code=404, detail="Dealer non trovato")

    # controlla presenza cliente esistente (per CF o P.IVA)
    cliente_esistente = None

    if cliente.tipo_cliente == "Privato":
        cliente_esistente = db.query(Cliente).filter(
            Cliente.codice_fiscale == cliente.codice_fiscale
        ).first()

    elif cliente.tipo_cliente in ["Società", "Professionista"]:
        cliente_esistente = db.query(Cliente).filter(
            Cliente.partita_iva == cliente.partita_iva
        ).first()

    if cliente_esistente:
        raise HTTPException(status_code=400, detail="Cliente già presente")

    # Inserisce nuovo cliente
    nuovo_cliente = Cliente(
        admin_id=dealer.parent_id or dealer.id,
        dealer_id=None if dealer.role == "admin" else dealer.id,
        tipo_cliente=cliente.tipo_cliente,
        nome=cliente.nome,
        cognome=cliente.cognome,
        ragione_sociale=cliente.ragione_sociale if cliente.tipo_cliente == "Società" else None,
        codice_fiscale=cliente.codice_fiscale,
        partita_iva=cliente.partita_iva,
        indirizzo=cliente.indirizzo,
        telefono=cliente.telefono,
        email=cliente_pubblico.email,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
    )

    db.add(nuovo_cliente)

    # conferma cliente pubblico
    cliente_pubblico.confermato = True
    db.commit()
    db.refresh(nuovo_cliente)

    
    # Genera il PDF e invia mail asincrona
    background_tasks.add_task(
        genera_e_invia_preventivo,
        cliente_pubblico_token=cliente_pubblico.token,
        slug_offerta=cliente_pubblico.slug_offerta,
        dealer_slug=cliente_pubblico.dealer_slug,
        tipo_cliente=cliente.tipo_cliente,
        cliente_id=nuovo_cliente.id,
        dealer_id=dealer.id
    )

    return {
        "success": True,
        "status": "cliente_creato",
        "message": "Dati ricevuti correttamente! Riceverai presto il preventivo via email.",
        "cliente_token": cliente_pubblico.token  # <--- passa token già esistente e subito disponibile
    }



from sqlalchemy.orm import sessionmaker
import httpx


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# Configurazione Supabase confermata
SUPABASE_URL = "https://vqfloobaovtdtcuflqeu.supabase.co"
SUPABASE_BUCKET = "nlt-preventivi"
SUPABASE_API_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InZxZmxvb2Jhb3Z0ZHRjdWZscWV1Iiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTczOTUzOTUzMCwiZXhwIjoyMDU1MTE1NTMwfQ.Lq-uIgXYZiBJK4ChfF_D7i5qYBDuxMfL2jY5GGKDuVk"

async def genera_e_invia_preventivo(
    cliente_pubblico_token,
    slug_offerta,
    dealer_slug,
    tipo_cliente,
    cliente_id,
    dealer_id
):
    db_session = SessionLocal()

    try:
        cliente_pubblico = db_session.query(NltClientiPubblici).filter(
            NltClientiPubblici.token == cliente_pubblico_token
        ).first()
        cliente = db_session.query(Cliente).get(cliente_id)
        dealer = db_session.query(User).get(dealer_id)
        offerta = db_session.query(NltOfferte).filter(NltOfferte.slug == slug_offerta).first()

        dealer_settings = db_session.query(SiteAdminSettings).filter(SiteAdminSettings.slug == dealer_slug).first()
        admin = db_session.query(User).get(dealer_settings.admin_id)

        servizi = db_session.query(NltService).filter(NltService.is_active == True).all()
        documenti = db_session.query(NltDocumentiRichiesti).filter(NltDocumentiRichiesti.tipo_cliente == tipo_cliente).all()

        payload_pdf = {
            "CustomerFirstName": cliente.nome,
            "CustomerLastName": cliente.cognome,
            "CustomerCompanyName": cliente.ragione_sociale or "",
            "TipoCliente": tipo_cliente,
            "DocumentiNecessari": [doc.documento for doc in documenti],
            "CarMainImageUrl": f"{offerta.default_img}&angle=203&width=800",
            "CarImages": [
                {"Url": f"{offerta.default_img}&angle={angle}&width=800", "Angle": angle, "Color": "N.D."}
                for angle in [29, 17, 13, 9, 21]
            ],
            "Auto": {
                "Marca": offerta.marca,
                "Modello": offerta.modello,
                "Versione": offerta.versione,
                "DescrizioneVersione": offerta.versione,
                "Note": "Richiesta preventivo web"
            },
            "Servizi": [{"Nome": s.name, "Opzione": s.conditions["options"][0]} for s in servizi],
            "DatiEconomici": {
                "Durata": cliente_pubblico.durata,
                "KmTotali": cliente_pubblico.km,
                "Anticipo": cliente_pubblico.anticipo,
                "Canone": cliente_pubblico.canone
            },
            "AdminInfo": {
                "Email": admin.email,
                "CompanyName": admin.ragione_sociale,
                "LogoUrl": admin.logo_url
            },
            "DealerInfo": {
                "Email": dealer.email,
                "CompanyName": dealer.ragione_sociale,
                "LogoUrl": dealer.logo_url
            } if dealer else None,
            "NoteAuto": "Richiesta da sito web",
            "Player": "Web"
        }

        async with httpx.AsyncClient(timeout=120) as client:
            pdf_res = await client.post("https://corewebapp-azcore.up.railway.app/api/Pdf/GenerateOffer", json=payload_pdf)
            pdf_res.raise_for_status()
            pdf_blob = pdf_res.content

        file_name = f"{uuid.uuid4()}.pdf"
        file_path = f"{SUPABASE_BUCKET}/{file_name}"

        async with httpx.AsyncClient(timeout=120) as client:
            upload_res = await client.put(
                f"{SUPABASE_URL}/storage/v1/object/{file_path}",
                headers={"Authorization": f"Bearer {SUPABASE_API_KEY}", "Content-Type": "application/pdf"},
                content=pdf_blob
            )
            upload_res.raise_for_status()

        file_url = f"{SUPABASE_URL}/storage/v1/object/public/{file_path}"

        nuovo_preventivo = NltPreventivi(
            cliente_id=cliente.id,
            file_url=file_url,
            creato_da=dealer.id,
            marca=offerta.marca,
            modello=offerta.modello,
            versione=offerta.versione,
            durata=cliente_pubblico.durata,
            km_totali=cliente_pubblico.km,
            anticipo=cliente_pubblico.anticipo,
            canone=cliente_pubblico.canone,
            visibile=1,
            preventivo_assegnato_a=dealer.id,
            note="Richiesta web",
            player="Web"
        )
        db_session.add(nuovo_preventivo)
        db_session.commit()

        # Usa admin.id per email SMTP
        send_email(admin.id, cliente.email, "Il tuo preventivo è pronto!", f"Scarica il preventivo: {file_url}")

    except Exception as e:
        db_session.rollback()
        print(f"[ERRORE ASINCRONO DETTAGLIATO]: {str(e)}")

    finally:
        db_session.close()

