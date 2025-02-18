from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.database import SessionLocal
from app.models import User
from app.routes.auth import get_current_user
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr, Field

router = APIRouter()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Funzione per ottenere il database
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Modello per la creazione di un Admin
class AdminCreateRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    nome: str
    cognome: str
    indirizzo: str
    cap: str
    citta: str
    cellulare: str
    ragione_sociale: str | None = None
    partita_iva: str | None = None
    codice_sdi: str | None = None
    credit: float = 0.0  # Gli admin iniziano con 0 credito

# Endpoint per ottenere tutti gli utenti (solo per superadmin)
# Endpoint per ottenere tutti gli utenti (solo per superadmin)
@router.get("/")
def get_users(Authorize: AuthJWT = Depends(), db: Session = Depends(get_db)):
    Authorize.jwt_required()
    user_data = Authorize.get_jwt_subject()
    user = db.query(User).filter(User.email == user_data).first()

    if not user or user.role != "superadmin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Accesso negato")
    
    users = db.query(User).all()
    return users


# Creazione di un Admin (solo per Superadmin)
@router.post("/admin")
def create_admin(admin_data: AdminCreateRequest, user_data: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    if user_data["role"] != "superadmin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Accesso negato")

    # Controlliamo se l'email esiste già
    if db.query(User).filter(User.email == admin_data.email).first():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email già in uso")

    hashed_password = pwd_context.hash(admin_data.password)

    new_admin = User(
        email=admin_data.email,
        hashed_password=hashed_password,
        role="admin",  # Il ruolo viene assegnato automaticamente
        nome=admin_data.nome,
        cognome=admin_data.cognome,
        indirizzo=admin_data.indirizzo,
        cap=admin_data.cap,
        citta=admin_data.citta,
        cellulare=admin_data.cellulare,
        ragione_sociale=admin_data.ragione_sociale,
        partita_iva=admin_data.partita_iva,
        codice_sdi=admin_data.codice_sdi,
        credit=0.0
    )

    db.add(new_admin)
    db.commit()
    db.refresh(new_admin)

    return {"message": "Admin creato con successo", "user": new_admin}

# Funzione per ottenere i costi dal database
from sqlalchemy import text

def get_costs(db: Session):
    query = text("SELECT dealer_activation_cost, dealer_monthly_cost FROM settings")
    result = db.execute(query).fetchone()

    if result is None:
        raise ValueError("⚠️ ERRORE: Nessun valore di costo trovato nella tabella settings!")

    dealer_activation_cost, dealer_monthly_cost = result  # Estrarre i valori correttamente

    return dealer_activation_cost, dealer_monthly_cost

class DealerCreateRequest(BaseModel):
    email: str
    password: str
    nome: str
    cognome: str
    indirizzo: str
    cap: str
    citta: str
    cellulare: str
    ragione_sociale: str | None = None
    partita_iva: str | None = None
    codice_sdi: str | None = None

@router.post("/dealer")
def create_dealer(
    dealer_data: DealerCreateRequest,  # Corretto il tipo
    user_data: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if user_data["role"] != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Accesso negato")

    dealer_activation_cost, dealer_monthly_cost = get_costs(db)

    if user_data["credit"] < dealer_activation_cost + dealer_monthly_cost:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Credito insufficiente. Servono almeno {dealer_activation_cost + dealer_monthly_cost} crediti."
        )

    if db.query(User).filter(User.email == dealer_data.email).first():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email già in uso")

    hashed_password = pwd_context.hash(dealer_data.password)

    new_dealer = User(
        email=dealer_data.email,
        hashed_password=hashed_password,
        role="dealer",
        nome=dealer_data.nome,
        cognome=dealer_data.cognome,
        indirizzo=dealer_data.indirizzo,
        cap=dealer_data.cap,
        citta=dealer_data.citta,
        cellulare=dealer_data.cellulare,
        ragione_sociale=dealer_data.ragione_sociale,
        partita_iva=dealer_data.partita_iva,
        codice_sdi=dealer_data.codice_sdi,
        credit=0.0,
        parent_id=user_data["user"].id
    )

    admin_user = db.query(User).filter(User.email == user_data["user"].email).first()
    admin_user.credit -= dealer_activation_cost + dealer_monthly_cost
    print(f"🔍 DEBUG: Credito Admin aggiornato. Nuovo saldo: {admin_user.credit}")

    db.add(new_dealer)
    db.commit()
    db.refresh(new_dealer)
    db.refresh(admin_user)

    return {
        "message": f"Dealer creato con successo. Credito rimanente: {admin_user.credit}",
        "user": new_dealer
    }