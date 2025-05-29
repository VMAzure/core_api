from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks, Body  
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from app.database import get_db, engine  # sostituisci con import corretto

from app.models import User, Cliente, ClienteModifica, NltPreventivi, NltPreventiviLinks, NltClientiPubblici, SiteAdminSettings
from fastapi_jwt_auth import AuthJWT
from typing import List, Optional
from app.schemas import ClienteResponse, ClienteCreateRequest, NltClientiPubbliciCreate, NltClientiPubbliciResponse
from fastapi import Query, Body, BackgroundTasks

from pydantic import BaseModel, EmailStr

import uuid
from app.utils.email import send_email
from sqlalchemy import or_, func
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
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    # Trova il dealer richiesto usando il dealer_slug fornito
    dealer = db.query(User).join(
        SiteAdminSettings,
        ((SiteAdminSettings.dealer_id == User.id) | ((SiteAdminSettings.dealer_id == None) & (SiteAdminSettings.admin_id == User.id)))
    ).filter(SiteAdminSettings.slug == payload.dealer_slug).first()

    if not dealer:
        raise HTTPException(status_code=404, detail="Dealer non trovato.")

    # Controlla se esiste già un cliente con questa email
    cliente_esistente = db.query(Cliente).filter(Cliente.email.ilike(payload.email)).first()

    # Genera un nuovo token e le date associate
    token = str(uuid.uuid4())
    data_creazione = datetime.utcnow()
    data_scadenza = data_creazione + timedelta(days=7)

    # Determina lo stato cliente in base al cliente esistente
    if cliente_esistente:
        if (
            (cliente_esistente.dealer_id is not None and cliente_esistente.dealer_id == dealer.id) or
            (cliente_esistente.dealer_id is None and cliente_esistente.admin_id == dealer.id)
        ):
            stato_cliente = "cliente_stesso_dealer"
            confermato = True
        else:
            stato_cliente = "cliente_altro_dealer"
            confermato = False
    else:
        stato_cliente = "nuovo_cliente"
        confermato = False

    # Recupera il record esistente (se presente)
    cliente_pubblico = db.query(NltClientiPubblici).filter_by(
        email=payload.email,
        dealer_slug=payload.dealer_slug
    ).order_by(NltClientiPubblici.data_creazione.desc()).first()

    if cliente_pubblico:
    # 🚨 Non generare nuovo token se già confermato!
        token = cliente_pubblico.token if cliente_pubblico.confermato else str(uuid.uuid4())

        cliente_pubblico.token = token
        cliente_pubblico.data_creazione = data_creazione
        cliente_pubblico.data_scadenza = data_scadenza
        cliente_pubblico.slug_offerta = payload.slug_offerta
        cliente_pubblico.anticipo = payload.anticipo
        cliente_pubblico.canone = payload.canone
        cliente_pubblico.durata = payload.durata
        cliente_pubblico.km = payload.km
        cliente_pubblico.confermato = confermato
    else:
        token = str(uuid.uuid4())  # genera token solo se record nuovo
        cliente_pubblico = NltClientiPubblici(
            email=payload.email,
            dealer_slug=payload.dealer_slug,
            token=token,
            data_creazione=data_creazione,
            data_scadenza=data_scadenza,
            confermato=confermato,
            slug_offerta=payload.slug_offerta,
            anticipo=payload.anticipo,
            canone=payload.canone,
            durata=payload.durata,
            km=payload.km
        )
        db.add(cliente_pubblico)

    db.commit()
    db.refresh(cliente_pubblico)


    # Doppia verifica sicurezza (token aggiornato correttamente)
    if cliente_pubblico.token != token:
        cliente_pubblico.token = token
        db.commit()
        db.refresh(cliente_pubblico)

    # 🚩 Qui gestiamo subito l'invio del preventivo se il cliente è già confermato
    if stato_cliente == "cliente_stesso_dealer" and cliente_esistente:
        background_tasks.add_task(
            genera_e_invia_preventivo,
            cliente_pubblico_token=cliente_pubblico.token,  # assicurato token corretto
            slug_offerta=payload.slug_offerta,
            dealer_slug=payload.dealer_slug,
            tipo_cliente=cliente_esistente.tipo_cliente,
            cliente_id=cliente_esistente.id,
            dealer_id=dealer.id,
            db=db
        )

    # ✅ Risposta finale definitiva al frontend con i dati aggiornati
    return NltClientiPubbliciResponse(
        id=cliente_pubblico.id,
        email=cliente_pubblico.email,
        dealer_slug=cliente_pubblico.dealer_slug,
        token=cliente_pubblico.token,  # garantito aggiornato
        data_creazione=cliente_pubblico.data_creazione,
        data_scadenza=cliente_pubblico.data_scadenza,
        confermato=cliente_pubblico.confermato,
        stato=stato_cliente,
        email_esistente=cliente_esistente.email if cliente_esistente else None,
        dealer_corrente=payload.dealer_slug if stato_cliente == "cliente_altro_dealer" else None,
        id_cliente=cliente_esistente.id if cliente_esistente else None,
        assegnatario_nome=cliente_esistente.dealer.ragione_sociale if cliente_esistente and cliente_esistente.dealer else None
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
        dealer_id=dealer.id,
        db=db  # 👈 aggiungi questa riga

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
    dealer_id,
    db: Session
):

    try:
        cliente_pubblico = db.query(NltClientiPubblici).filter(
            NltClientiPubblici.token == cliente_pubblico_token
        ).first()

        cliente = db.query(Cliente).get(cliente_id)
        dealer = db.query(User).get(dealer_id)
        offerta = db.query(NltOfferte).filter(NltOfferte.slug == slug_offerta).first()

        dealer_settings = db.query(SiteAdminSettings).filter(SiteAdminSettings.slug == dealer_slug).first()
        admin = db.query(User).get(dealer_settings.admin_id)

        servizi = db.query(NltService).filter(NltService.is_active == True).all()
        documenti = db.query(NltDocumentiRichiesti).filter(NltDocumentiRichiesti.tipo_cliente == tipo_cliente).all()

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
            pdf_res = await client.post(
                "https://corewebapp-azcore.up.railway.app/api/Pdf/GenerateOffer", 
                json=payload_pdf
            )
            pdf_res.raise_for_status()
            pdf_blob = pdf_res.content

        file_name = f"{uuid.uuid4()}.pdf"
        file_path = f"{SUPABASE_BUCKET}/{file_name}"

        async with httpx.AsyncClient(timeout=120) as client:
            upload_res = await client.put(
                f"{SUPABASE_URL}/storage/v1/object/{file_path}",
                headers={
                    "Authorization": f"Bearer {SUPABASE_API_KEY}",
                    "Content-Type": "application/pdf"
                },
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

        db.add(nuovo_preventivo)
        db.commit()
        db.refresh(nuovo_preventivo)

        preventivo_id = nuovo_preventivo.id
        print(f"✅ Preventivo creato con ID: {preventivo_id}")

    except Exception as e:
        db.rollback()
        print(f"❌ ERRORE inserimento preventivo: {str(e)}")
        return  # importante: esci qui se errore

    # Questo codice DEVE essere fuori dal blocco try-except!
    async with httpx.AsyncClient() as client:
        response_link = await client.post(
            f"https://coreapi-production-ca29.up.railway.app/nlt/preventivi/{preventivo_id}/genera-link"
        )
        response_link.raise_for_status()
        link_data = response_link.json()
        url_download = link_data["url_download"]

        response_dettagli = await client.get(
            f"https://coreapi-production-ca29.up.railway.app/nlt/preventivo-completo/{preventivo_id}?dealerId={dealer.id}"
        )
        response_dettagli.raise_for_status()
        dettagli = response_dettagli.json()

        template_html_res = await client.get(
            'https://corewebapp-azcore.up.railway.app/templates/email_preventivo.html'
        )
        template_html_res.raise_for_status()
        template_html = template_html_res.text

        from jinja2 import Template
        template = Template(template_html)
        html_body = template.render(
            logo_url=dettagli["DealerInfo"]["LogoUrl"],
            cliente_nome=f"{dettagli['CustomerFirstName']} {dettagli['CustomerLastName']}",
            marca=dettagli["Auto"]["Marca"],
            modello=dettagli["Auto"]["Modello"],
            url_download=url_download,
            dealer_name=dettagli["DealerInfo"]["CompanyName"],
            indirizzo=dettagli["DealerInfo"]["Address"],
            citta=dettagli["DealerInfo"]["City"],
            telefono=dettagli["DealerInfo"]["MobilePhone"],
            email=dettagli["DealerInfo"]["Email"]
        )

        await client.post(
            f"https://coreapi-production-ca29.up.railway.app/nlt/preventivi/{preventivo_id}/invia-mail",
            json={
                "url_download": url_download,
                "to_email": dettagli["CustomerEmail"],
                "subject": f"Il tuo preventivo {dettagli['Auto']['Marca']} {dettagli['Auto']['Modello']} è pronto",
                "html_body": html_body
            }
        )

@router.put("/public/clienti/switch-anagrafica")
def switch_anagrafica_cliente_pubblico(
    payload: dict = Body(...),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    db: Session = Depends(get_db)
):
    email_cliente = payload.get("email_cliente")
    nuovo_dealer_slug = payload.get("nuovo_dealer_slug")
    nuova_email = payload.get("nuova_email")

    if not email_cliente or not nuovo_dealer_slug or not nuova_email:
        raise HTTPException(status_code=400, detail="Parametri mancanti")

    cliente = db.query(Cliente).filter(Cliente.email.ilike(email_cliente)).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente non trovato")

    # Cerca lo slug tra i dealer
    dealer_settings = db.query(SiteAdminSettings).filter(SiteAdminSettings.slug == nuovo_dealer_slug).first()
    if not dealer_settings:
        raise HTTPException(status_code=404, detail="Slug dealer non trovato")

    # Prova a trovare il dealer reale
    if dealer_settings.dealer_id:
        nuovo_dealer = db.query(User).filter(User.id == dealer_settings.dealer_id).first()
    else:
        # Fallback su admin
        nuovo_dealer = db.query(User).filter(User.id == dealer_settings.admin_id).first()

    if not nuovo_dealer:
        raise HTTPException(status_code=404, detail="Dealer o Admin non trovato")

    # aggiorna assegnazione del cliente
    cliente.dealer_id = nuovo_dealer.id
    db.commit()

    # aggiorna anche la tabella dei pubblici
    cliente_pubblico = db.query(NltClientiPubblici).filter_by(email=email_cliente).order_by(
        NltClientiPubblici.data_creazione.desc()
    ).first()

    if not cliente_pubblico:
        raise HTTPException(status_code=404, detail="Cliente pubblico non trovato")

    cliente_pubblico.dealer_slug = nuovo_dealer_slug
    db.commit()

    # Attiva la generazione e invio preventivo
    background_tasks.add_task(
        genera_e_invia_preventivo,
        cliente_pubblico_token=cliente_pubblico.token,
        slug_offerta=cliente_pubblico.slug_offerta,
        dealer_slug=nuovo_dealer_slug,
        tipo_cliente=cliente.tipo_cliente,
        cliente_id=cliente.id,
        dealer_id=nuovo_dealer.id,
        db=db
    )

    return {
        "success": True,
        "message": "Cliente riassegnato e preventivo in invio."
    }


@router.post("/public/clienti/forza-invio")
def forza_invio_preventivo_cliente_pubblico(
    token: str = Query(...),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    db: Session = Depends(get_db)
):
    cliente_pubblico = db.query(NltClientiPubblici).filter_by(token=token).first()
    if not cliente_pubblico:
        raise HTTPException(status_code=404, detail="Token non trovato")

    cliente = db.query(Cliente).filter(Cliente.email.ilike(cliente_pubblico.email)).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente non trovato")

    # Recupera il dealer corretto dal cliente
    dealer = db.query(User).filter(User.id == cliente.dealer_id).first()
    if not dealer:
        raise HTTPException(status_code=404, detail="Dealer non trovato")

    # Recupera lo slug effettivo del dealer dai settings
    settings = db.query(SiteAdminSettings).filter(
        (SiteAdminSettings.dealer_id == cliente.dealer_id) |
        ((SiteAdminSettings.dealer_id == None) & (SiteAdminSettings.admin_id == cliente.admin_id))
    ).first()
    if not settings:
        raise HTTPException(status_code=404, detail="Impostazioni dealer non trovate")

    # Avvia l'invio preventivo
    background_tasks.add_task(
        genera_e_invia_preventivo,
        cliente_pubblico_token=cliente_pubblico.token,
        slug_offerta=cliente_pubblico.slug_offerta,
        dealer_slug=settings.slug,
        tipo_cliente=cliente.tipo_cliente,
        cliente_id=cliente.id,
        dealer_id=dealer.id,
        db=db
    )

    return {
        "success": True,
        "message": "Preventivo inviato correttamente"
    }



class VerificaAnagraficaRequest(BaseModel):
    tipo_cliente: str
    codice_fiscale: str | None = None
    partita_iva: str | None = None
    email: str
    dealer_slug: str


@router.post("/public/clienti/verifica-anagrafica")
def verifica_anagrafica_cliente_pubblico(
    dati: VerificaAnagraficaRequest = Body(...),
    db: Session = Depends(get_db)
):
    if dati.tipo_cliente == "Privato":
        if not dati.codice_fiscale:
            raise HTTPException(status_code=400, detail="Codice fiscale mancante")
        filtro = func.upper(Cliente.codice_fiscale) == dati.codice_fiscale.upper()
    elif dati.tipo_cliente in ["Società", "Professionista"]:
        if not dati.partita_iva:
            raise HTTPException(status_code=400, detail="Partita IVA mancante")
        filtro = func.upper(Cliente.partita_iva) == dati.partita_iva.upper()
    else:
        raise HTTPException(status_code=400, detail="Tipo cliente non valido")

    cliente = db.query(Cliente).filter(filtro).first()
    if not cliente:
        return { "stato": "anagrafica_disponibile" }

    if cliente.email.lower() == dati.email.lower():
        return { "stato": "anagrafica_presente_stessa_email" }

    # Trova dealer corrente
    dealer_settings = db.query(SiteAdminSettings).filter_by(slug=dati.dealer_slug).first()
    if not dealer_settings:
        raise HTTPException(status_code=404, detail="Dealer non trovato")

    # Dealer origine (registrato) vs dealer corrente
    dealer_corrente_id = dealer_settings.dealer_id or dealer_settings.admin_id
    # Recupera lo slug corretto del dealer originario assegnato al cliente
    if cliente.dealer_id is not None:
        dealer_slug_settings = db.query(SiteAdminSettings).filter(
            SiteAdminSettings.dealer_id == cliente.dealer_id
        ).first()
    else:
        dealer_slug_settings = db.query(SiteAdminSettings).filter(
            SiteAdminSettings.dealer_id == None,
            SiteAdminSettings.admin_id == cliente.admin_id
        ).first()

    dealer_origine_slug = dealer_slug_settings.slug if dealer_slug_settings else None
    dealer_registrato_id = cliente.dealer_id or cliente.admin_id

    if dealer_corrente_id == dealer_registrato_id:
        return {
            "stato": "stesso_dealer_email_differente",
            "email_registrata": cliente.email,
            "id_cliente": cliente.id,
            "dealer_origine_slug": dealer_origine_slug
        }
    else:
        return {
            "stato": "altro_dealer_email_differente",
            "email_registrata": cliente.email,
            "dealer_origine_id": dealer_registrato_id,
            "id_cliente": cliente.id,
            "dealer_origine_slug": dealer_origine_slug
        }





class AggiornaEmailRequest(BaseModel):
    nuova_email: EmailStr
@router.put("/public/clienti/{cliente_id}/aggiorna-email")
def aggiorna_email_cliente_pubblico(
    cliente_id: int,
    payload: AggiornaEmailRequest,
    token: str = Query(...),  # token da frontend
    background_tasks: BackgroundTasks = BackgroundTasks(),
    db: Session = Depends(get_db)
):
    nuova_email = payload.nuova_email

    cliente = db.query(Cliente).filter(Cliente.id == cliente_id).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente non trovato")

    if cliente.email.lower() == nuova_email.lower():
        raise HTTPException(status_code=400, detail="Email identica")

    email_in_uso = db.query(Cliente).filter(Cliente.email.ilike(nuova_email)).first()
    if email_in_uso:
        raise HTTPException(status_code=409, detail="Email già associata a un altro cliente")

    cliente.email = nuova_email
    cliente.updated_at = datetime.utcnow()
    db.commit()

    # recupera cliente pubblico usando il token (più affidabile)
    cliente_pubblico = db.query(NltClientiPubblici).filter_by(token=token).first()
    if not cliente_pubblico:
        raise HTTPException(status_code=404, detail="Cliente pubblico non trovato")

    settings = db.query(SiteAdminSettings).filter_by(slug=cliente_pubblico.dealer_slug).first()
    if not settings:
        raise HTTPException(status_code=404, detail="Dealer non trovato")

    dealer_id = settings.dealer_id or settings.admin_id

    background_tasks.add_task(
        genera_e_invia_preventivo,
        cliente_pubblico_token=cliente_pubblico.token,
        slug_offerta=cliente_pubblico.slug_offerta,
        dealer_slug=cliente_pubblico.dealer_slug,
        tipo_cliente=cliente.tipo_cliente,
        cliente_id=cliente.id,
        dealer_id=dealer_id,
        db=db
    )

    return {
        "success": True,
        "message": "Email aggiornata. Preventivo in invio."
    }
