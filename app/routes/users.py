from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.database import SessionLocal
from app.models import User
from app.routes.auth import get_current_user  # ✅ Usa lo stesso metodo di auth.py
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr, Field
from fastapi_jwt_auth import AuthJWT  # Importiamo AuthJWT
from fastapi import UploadFile, File
import supabase
from supabase import create_client, Client
from app.schemas import UserUpdateRequest, ChangePasswordRequest



import os
from datetime import datetime

router = APIRouter()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Funzione per ottenere il database
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.options("/{full_path:path}")
async def preflight(full_path: str):
    """Gestisce le richieste pre-flight per evitare problemi di CORS"""
    return {"message": "OK"}


# Endpoint per ottenere tutti gli utenti (solo per superadmin)
@router.get("/")
def get_users(Authorize: AuthJWT = Depends(), db: Session = Depends(get_db)):
    Authorize.jwt_required()  # Verifica il token direttamente
    user_email = Authorize.get_jwt_subject()
    
    user = db.query(User).filter(User.email == user_email).first()
    if not user or user.role != "superadmin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Accesso negato")
    
    users = db.query(User).all()
    return users


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

# Creazione di un Admin (solo per Superadmin)
@router.post("/admin")
def create_admin(admin_data: AdminCreateRequest, Authorize: AuthJWT = Depends(), db: Session = Depends(get_db)):
    """
    API per la creazione di un nuovo Admin, accessibile solo ai Superadmin.
    - Controlla se il token è valido
    - Controlla se l'utente è un Superadmin
    - Verifica che l'email e la Partita IVA non siano già registrate
    - Crea il nuovo admin nel database
    """
    
    # ✅ Verifica del token
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()
    
    print(f"🔍 DEBUG: Token valido, utente autenticato: {user_email}")

    # ✅ Controlla se l'utente è Superadmin
    user = db.query(User).filter(User.email == user_email).first()
    if not user or user.role != "superadmin":
        print("⛔ DEBUG: Accesso negato, l'utente non è un superadmin")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Accesso negato")

    # ✅ Controllo se l'email è già in uso
    if db.query(User).filter(User.email == admin_data.email).first():
        print("⛔ DEBUG: Email già registrata")
        return {"status": "error", "message": "Email già in uso", "exists": True}

    # ✅ Controllo se la Partita IVA è già in uso
    if db.query(User).filter(User.partita_iva == admin_data.partita_iva).first():
        print("⛔ DEBUG: Partita IVA già registrata")
        return {"status": "error", "message": "Partita IVA già in uso", "exists": True}

    # ✅ Hash della password
    hashed_password = pwd_context.hash(admin_data.password)

    # ✅ Creazione del nuovo admin
    new_admin = User(
        email=admin_data.email,
        hashed_password=hashed_password,
        role="admin",
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

    print(f"✅ DEBUG: Admin creato con successo -> {new_admin.email}")

    return {
        "status": "success",
        "message": "Admin creato con successo",
        "user": {
            "id": new_admin.id,
            "email": new_admin.email,
            "nome": new_admin.nome,
            "cognome": new_admin.cognome,
            "ragione_sociale": new_admin.ragione_sociale,
            "partita_iva": new_admin.partita_iva,
            "codice_sdi": new_admin.codice_sdi,
            "credit": new_admin.credit
        }
    }


# Funzione per ottenere i costi dal database
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
    dealer_data: DealerCreateRequest,
    Authorize: AuthJWT = Depends(),  # 🔥 Sostituiamo get_current_user con AuthJWT
    db: Session = Depends(get_db)
):
    # ✅ Verifica del token JWT
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()

    # ✅ Recupera i dati dell'utente autenticato (Admin)
    admin_user = db.query(User).filter(User.email == user_email).first()
    if not admin_user or admin_user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Accesso negato")

    # ✅ Verifica credito sufficiente
    dealer_activation_cost, dealer_monthly_cost = get_costs(db)
    if admin_user.credit < dealer_activation_cost + dealer_monthly_cost:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Credito insufficiente. Servono almeno {dealer_activation_cost + dealer_monthly_cost} crediti."
        )

    # ✅ Controlla se l'email è già registrata
    if db.query(User).filter(User.email == dealer_data.email).first():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email già in uso")

    # ✅ Hash della password
    hashed_password = pwd_context.hash(dealer_data.password)

    # ✅ Creazione del nuovo dealer
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
        parent_id=admin_user.id
    )

    # ✅ Aggiornamento credito Admin
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


@router.get("/list", tags=["Users"])
def get_users_list(Authorize: AuthJWT = Depends(), db: Session = Depends(get_db)):
    """Restituisce l'elenco utenti: i Super Admin vedono tutti, gli Admin solo i loro Dealer."""
    
    # Verifica del token JWT
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()

    # Recupero informazioni utente
    user = db.query(User).filter(User.email == user_email).first()
    
    if not user:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Accesso negato")

    # Se l'utente è un Super Admin, restituisce tutti gli utenti
    if user.role == "superadmin":
        users = db.query(
            User.id,
            User.ragione_sociale,
            User.parent_id.label("admin_id"),
            User.email,
            User.partita_iva,
            User.indirizzo,
            User.created_at.label("activation_date"),
            User.updated_at,
            User.cap,
            User.citta,
            User.role,
            User.codice_sdi,
            User.nome,
            User.cognome,
            User.cellulare,
            User.credit,
            User.logo_url  # ✅ aggiungi questo

        ).order_by(User.id).all()
    
    # Se l'utente è un Admin, restituisce solo i suoi Dealer
    elif user.role == "admin":
        users = db.query(
            User.id,
            User.ragione_sociale,
            User.parent_id.label("admin_id"),
            User.email,
            User.partita_iva,
            User.indirizzo,
            User.created_at.label("activation_date"),
            User.updated_at,
            User.cap,
            User.citta,
            User.role,
            User.codice_sdi,
            User.nome,
            User.cognome,
            User.cellulare,
            User.credit,
            User.logo_url  # ✅ aggiungi questo

        ).filter(User.parent_id == user.id, User.role == "dealer").order_by(User.id).all()
    
    # Se l'utente ha un ruolo diverso, accesso negato
    else:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Accesso negato")

    # Convertiamo i risultati in formato JSON
    users_list = [
        {
            "id": u.id,
            "ragione_sociale": u.ragione_sociale,
            "admin_id": u.admin_id,
            "email": u.email,
            "partita_iva": u.partita_iva,
            "indirizzo": u.indirizzo,
            "activation_date": u.activation_date.isoformat() if u.activation_date else None,
            "updated_at": u.updated_at.isoformat() if u.updated_at else None,
            "cap": u.cap,
            "citta": u.citta,
            "role": u.role,
            "codice_sdi": u.codice_sdi,
            "nome": u.nome,
            "cognome": u.cognome,
            "cellulare": u.cellulare,
            "credit": u.credit,
            "logo_url": u.logo_url  # ✅ aggiungi questo

        }
        for u in users
    ]

    return users_list

@router.get("/credit", tags=["Users"])
def get_user_credit(Authorize: AuthJWT = Depends(), db: Session = Depends(get_db)):
    """
    API per ottenere il credito dell'utente autenticato.
    - Recupera l'utente dal token JWT.
    - Restituisce il credito disponibile.
    """
    # ✅ Verifica del token JWT
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()

    # ✅ Recupero informazioni utente
    user = db.query(User).filter(User.email == user_email).first()

    if not user:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Utente non trovato")

    return {"email": user.email, "credit": user.credit}



SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

supabase_client: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# endpoint upload-logo (finisce qui)
@router.post("/upload-logo", tags=["Users"])
async def upload_logo(file: UploadFile = File(...), Authorize: AuthJWT = Depends(), db: Session = Depends(get_db)):
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()

    user = db.query(User).filter(User.email == user_email).first()
    if not user or user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Accesso negato")

    if file.content_type not in ["image/png", "image/jpeg", "image/jpg"]:
        raise HTTPException(status_code=400, detail="Formato immagine non supportato")

    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    file_name = f"logos/{user.id}_{timestamp}_{file.filename}"

    try:
        content = await file.read()

        response = supabase_client.storage.from_("logos").upload(
            file_name, 
            content, 
            {"content-type": file.content_type}
        )

        image_url = f"{SUPABASE_URL}/storage/v1/object/public/logos/{file_name}"

        user.logo_url = image_url
        db.commit()
        db.refresh(user)

        return {"message": "Logo caricato con successo", "logo_url": image_url}

    except Exception as e:
        print(f"❌ Errore durante l'upload su Supabase: {e}")
        raise HTTPException(status_code=500, detail=f"Errore interno: {str(e)}")


# endpoint me (correttamente separato!)
@router.get("/me", tags=["Users"])
def get_my_profile(Authorize: AuthJWT = Depends(), db: Session = Depends(get_db)):
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()

    try:
        user = db.query(User).filter(User.email == user_email).first()

        if not user:
            raise HTTPException(status_code=404, detail="Utente non trovato")

        data = {
            "id": user.id,
            "email": user.email,
            "nome": user.nome,
            "cognome": user.cognome,
            "ragione_sociale": user.ragione_sociale,
            "partita_iva": user.partita_iva,
            "indirizzo": user.indirizzo,
            "cap": user.cap,
            "citta": user.citta,
            "codice_sdi": user.codice_sdi,
            "cellulare": user.cellulare,
            "credit": user.credit,
            "logo_url": user.logo_url,
            "created_at": user.created_at.isoformat() if user.created_at else None,
            "updated_at": user.updated_at.isoformat() if user.updated_at else None
        }

        if user.role == "dealer":
            admin = db.query(User).filter(User.id == user.parent_id).first()
            data["logo_url"] = admin.logo_url if admin else None

        return data

    except Exception as e:
        print(f"❌ ERRORE DETTAGLIATO endpoint /me: {e}")
        raise HTTPException(status_code=500, detail=f"Errore interno dettagliato: {str(e)}")

# Modello Pydantic per aggiornamento utente
class UserUpdateRequest(BaseModel):
    nome: str
    cognome: str
    indirizzo: str
    cap: str
    citta: str
    cellulare: str

@router.put("/update-profile", tags=["Users"])
def update_user_profile(
    user_data: UserUpdateRequest,
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()

    user = db.query(User).filter(User.email == user_email).first()

    if not user:
        raise HTTPException(status_code=404, detail="Utente non trovato")

    user.nome = user_data.nome
    user.cognome = user_data.cognome
    user.indirizzo = user_data.indirizzo
    user.cap = user_data.cap
    user.citta = user_data.citta
    user.cellulare = user_data.cellulare
    user.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(user)

    return {"message": "Profilo aggiornato con successo", "user": {
        "nome": user.nome,
        "cognome": user.cognome,
        "indirizzo": user.indirizzo,
        "cap": user.cap,
        "citta": user.citta,
        "cellulare": user.cellulare
    }}


