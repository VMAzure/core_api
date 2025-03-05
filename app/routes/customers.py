from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime
from app.database import get_db
from app.models import User, Cliente, ClienteModifica
from fastapi_jwt_auth import AuthJWT
from typing import List, Optional
from app.schemas import ClienteResponse, ClienteCreateRequest
from pydantic import BaseModel

router = APIRouter()

# Recupero lista clienti in base al ruolo
@router.get("/clienti", response_model=List[ClienteResponse])
def get_clienti(Authorize: AuthJWT = Depends(), db: Session = Depends(get_db)):
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()

    user = db.query(User).filter(User.email == user_email).first()
    if not user:
        raise HTTPException(status_code=404, detail="Utente non trovato")

    if user.role == "superadmin":
        clienti = db.query(Cliente).all()

    elif user.role == "admin":
        clienti = db.query(Cliente).filter(
            (Cliente.admin_id == user.id) |
            (Cliente.admin_id.in_([dealer.id for dealer in user.dealers]))
        ).all()

    elif user.role == "dealer":
        clienti = db.query(Cliente).filter(Cliente.dealer_id == user.id).all()

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
    admin_id = user.parent_id if user.role == "dealer" else user.id
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

    admin_id = user.parent_id if user.role == "dealer" else user.id
    dealer_id = user.id if user.role == "dealer" else None

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
    if not user or user.role != "dealer":
        raise HTTPException(status_code=403, detail="Accesso non autorizzato")

    cliente = db.query(Cliente).filter(Cliente.id == cliente_id, Cliente.dealer_id == user.id).first()
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
    if not user or user.role not in ["admin", "superadmin"]:
        raise HTTPException(status_code=403, detail="Accesso non autorizzato")

    cliente = db.query(Cliente).filter(Cliente.id == cliente_id).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente non trovato")

    for key, value in dati_cliente.dict().items():
        setattr(cliente, key, value)

    cliente.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(cliente)

    return {"msg": "Cliente modificato correttamente", "cliente": cliente}


