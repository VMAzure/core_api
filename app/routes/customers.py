from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from app.database import get_db
from app.models import User, Cliente, ClienteModifica, NltPreventivi, NltPreventiviLinks, NltClientiPubblici, SiteAdminSettings
from fastapi_jwt_auth import AuthJWT
from typing import List, Optional
from app.schemas import ClienteResponse, ClienteCreateRequest, NltClientiPubbliciCreate, NltClientiPubbliciResponse

from pydantic import BaseModel
import uuid
from app.utils.email import send_email




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


from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import User, Cliente, NltClientiPubblici, SiteAdminSettings
from app.utils.email import send_email
from app.schemas import NltClientePublicoCreateRequest, NltClientePublicoResponse
from datetime import datetime, timedelta
import uuid

router = APIRouter()

@router.post("/public/clienti", response_model=NltClientePublicoResponse)
def crea_cliente_pubblico(
    payload: NltClientePublicoCreateRequest,
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

    stato_cliente = "nuovo_cliente"
    if cliente_esistente:
        if cliente_esistente.dealer_id == dealer.id:
            stato_cliente = "cliente_stesso_dealer"
        else:
            stato_cliente = "cliente_altro_dealer"

    # Salva nella tabella NltClientiPubblici
    nuovo_cliente_pubblico = NltClientiPubblici(
        email=payload.email,
        dealer_slug=payload.dealer_slug,
        token=token,
        data_creazione=data_creazione,
        data_scadenza=data_scadenza,
        confermato=False
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

    try:
        send_email(admin_id, payload.email, subject, body)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Errore invio email: {str(e)}")

    return NltClientePublicoResponse(
        email=payload.email,
        dealer_slug=payload.dealer_slug,
        stato=stato_cliente,
        token=token,
        data_scadenza=data_scadenza
    )


@router.get("/public/clienti/conferma/{token}")
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
    ).filter(
        SiteAdminSettings.slug == cliente_pubblico.dealer_slug
    ).first()

    if not dealer_richiesto:
        raise HTTPException(status_code=404, detail="Dealer non trovato per slug fornito")

    response = {
        "email": cliente_pubblico.email,
        "dealer_richiesto": {
            "id": dealer_richiesto.id,
            "nome": dealer_richiesto.nome,
            "ragione_sociale": dealer_richiesto.ragione_sociale
        },
        "token": token,
        "stato": ""
    }

    if cliente_esistente:
        dealer_esistente = db.query(User).filter(User.id == cliente_esistente.dealer_id).first()
        response["cliente"] = {
            "id": cliente_esistente.id,
            "nome": cliente_esistente.nome,
            "cognome": cliente_esistente.cognome,
            "tipo_cliente": cliente_esistente.tipo_cliente,
            "dealer_attuale": {
                "id": dealer_esistente.id,
                "nome": dealer_esistente.nome,
                "ragione_sociale": dealer_esistente.ragione_sociale
            }
        }
        if dealer_esistente.id == dealer_richiesto.id:
            response["stato"] = "cliente_esistente"
        else:
            response["stato"] = "conflitto_dealer"
    else:
        response["stato"] = "nuovo_cliente"

    return response

