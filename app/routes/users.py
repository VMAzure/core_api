﻿from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.database import SessionLocal
from app.models import User, TeamMemberUpdateRequest
from app.routes.auth import get_current_user  
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr, Field
from fastapi_jwt_auth import AuthJWT  # Importiamo AuthJWT
from fastapi import UploadFile, File
import supabase
from supabase import create_client, Client
from app.schemas import UserUpdateRequest, ChangePasswordRequest, AdminTeamCreateRequest, DealerTeamCreateRequest
from app.auth_helpers import (
    get_admin_id,
    get_dealer_id,
    is_admin_user,
    is_dealer_user
)

import os
from fastapi import BackgroundTasks
import secrets
from datetime import datetime, timedelta
from app.utils.email import send_reset_email


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
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    # ✅ Verifica del token JWT
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()

    # ✅ Recupera i dati dell'utente autenticato (Admin)
    admin_user = db.query(User).filter(User.email == user_email).first()
    if not admin_user or not is_admin_user(admin_user):
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

    # 🔐 Controllo partita IVA di un altro Admin
    existing_admin = db.query(User).filter(
        User.partita_iva == dealer_data.partita_iva,
        User.role == "admin",
        User.id != admin_user.id
    ).first()

    if existing_admin:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Non puoi utilizzare la partita IVA di un altro Admin."
        )

    # ✅ Hash della password
    hashed_password = pwd_context.hash(dealer_data.password)

    # ✅ Creazione del nuovo dealer
    parent_id = get_admin_id(admin_user)

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
        parent_id=parent_id,
        shared_customers=(dealer_data.partita_iva == admin_user.partita_iva)  # 🔥 Automatico
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
    elif is_admin_user(user):
        admin_id = get_admin_id(user)
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
            User.logo_url
        ).filter(
            User.parent_id == admin_id,
            User.role.in_(["dealer", "dealer_team"])
        ).order_by(User.id).all()

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


# endpoint me aggiornato
from app.auth_helpers import get_admin_id, get_dealer_id

@router.get("/me", tags=["Users"])
def get_my_profile(Authorize: AuthJWT = Depends(), db: Session = Depends(get_db)):
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()

    try:
        user = db.query(User).filter(User.email == user_email).first()

        if not user:
            raise HTTPException(status_code=404, detail="Utente non trovato")

        # Dati base dell'utente loggato
        user_data = {
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

        response = {
            "role": user.role,
            "admin_info": None,
            "dealer_info": None
        }

        if user.role in ["dealer", "dealer_team"]:
            dealer_id = get_dealer_id(user)
            dealer = db.query(User).filter(User.id == dealer_id).first()

            response["dealer_info"] = {
                "id": user.id,
                "email": user.email,
                "nome": user.nome,
                "cognome": user.cognome,
                "cellulare": user.cellulare,
                "ragione_sociale": user.ragione_sociale or f"{user.nome} {user.cognome}"

            }

            response["admin_info"] = {
                "id": dealer.parent.id if dealer.parent else None,
                "email": dealer.parent.email if dealer.parent else None,
                "nome": dealer.parent.nome if dealer.parent else None,
                "cognome": dealer.parent.cognome if dealer.parent else None,
                "ragione_sociale": dealer.parent.ragione_sociale if dealer.parent else None,
                "partita_iva": dealer.parent.partita_iva if dealer.parent else None,
                "indirizzo": dealer.parent.indirizzo if dealer.parent else None,
                "cap": dealer.parent.cap if dealer.parent else None,
                "citta": dealer.parent.citta if dealer.parent else None,
                "codice_sdi": dealer.parent.codice_sdi if dealer.parent else None,
                "cellulare": dealer.parent.cellulare if dealer.parent else None,
                "credit": dealer.parent.credit if dealer.parent else None,
                "logo_url": dealer.parent.logo_url if dealer.parent else None,
                "created_at": dealer.parent.created_at.isoformat() if dealer.parent and dealer.parent.created_at else None,
                "updated_at": dealer.parent.updated_at.isoformat() if dealer.parent and dealer.parent.updated_at else None
            }

        elif user.role in ["admin", "admin_team"]:
            admin_id = get_admin_id(user)
            admin = db.query(User).filter(User.id == admin_id).first()

            response["admin_info"] = {
                "id": admin.id,
                "email": admin.email,
                "nome": user.nome if user.role == "admin_team" else admin.nome,
                "cognome": user.cognome if user.role == "admin_team" else admin.cognome,
                "ragione_sociale": admin.ragione_sociale,
                "partita_iva": admin.partita_iva,
                "indirizzo": admin.indirizzo,
                "cap": admin.cap,
                "citta": admin.citta,
                "codice_sdi": admin.codice_sdi,
                "cellulare": user.cellulare if user.role == "admin_team" else admin.cellulare,
                "credit": admin.credit,
                "logo_url": admin.logo_url,
                "created_at": admin.created_at.isoformat() if admin.created_at else None,
                "updated_at": admin.updated_at.isoformat() if admin.updated_at else None
            }


        return response

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

@router.post("/change-password", tags=["Users"])
def change_password(
    passwords: ChangePasswordRequest,
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()

    user = db.query(User).filter(User.email == user_email).first()

    if not user:
        raise HTTPException(status_code=404, detail="Utente non trovato")

    # Verifica vecchia password
    if not pwd_context.verify(passwords.old_password, user.hashed_password):
        raise HTTPException(status_code=401, detail="La password attuale non è corretta.")

    # Hash della nuova password
    hashed_password = pwd_context.hash(passwords.new_password)

    # Aggiorna password utente
    user.hashed_password = hashed_password
    user.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(user)

    return {"message": "Password aggiornata con successo!"}

@router.get("/dealers-assegnabili")
async def get_dealers_assegnabili(
    Authorize: AuthJWT = Depends(),  # Aggiunto questo
    db: Session = Depends(get_db)
):
    Authorize.jwt_required()  # ✅ Aggiunto esplicitamente questo
    user_email = Authorize.get_jwt_subject()
    current_user = db.query(User).filter(User.email == user_email).first()

    if not current_user:
        raise HTTPException(status_code=401, detail="Utente non trovato")

    if is_admin_user(current_user):
        admin_id = get_admin_id(current_user)
        dealers = db.query(User).filter(
            User.parent_id == admin_id,
            User.role == "dealer"
        ).all()


    elif current_user.role == "dealer":
        dealers = db.query(User).filter(
            User.parent_id == current_user.parent_id,
            User.role == "dealer",
            User.id != current_user.id
        ).all()

    else:
        dealers = []

    risultato = [{
        "id": dealer.id,
        "nome_completo": f"{dealer.nome} {dealer.cognome}".strip(),
        "email": dealer.email,
        "ragione_sociale": dealer.ragione_sociale,
        "partita_iva": dealer.partita_iva,
        "indirizzo": dealer.indirizzo,
        "cap": dealer.cap,
        "citta": dealer.citta,
        "codice_sdi": dealer.codice_sdi,
        "cellulare": dealer.cellulare,
        "logo_url": dealer.logo_url
    } for dealer in dealers]

    return {
        "success": True,
        "dealers": risultato
    }

@router.post("/admin-team", tags=["Users"])
def create_admin_team(
    user_data: AdminTeamCreateRequest,
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()
    admin = db.query(User).filter(User.email == user_email).first()

    if not admin or not is_admin_user(admin):
        raise HTTPException(status_code=403, detail="Accesso negato")

    # Email già registrata?
    if db.query(User).filter(User.email == user_data.email).first():
        raise HTTPException(status_code=400, detail="Email già in uso")

    hashed_password = pwd_context.hash(user_data.password)

    new_user = User(
        email=user_data.email,
        hashed_password=hashed_password,
        role="admin_team",
        nome=user_data.nome,
        cognome=user_data.cognome,
        cellulare=user_data.cellulare,
        indirizzo=admin.indirizzo,
        cap=admin.cap,
        citta=admin.citta,
        ragione_sociale=admin.ragione_sociale,
        partita_iva=admin.partita_iva,
        codice_sdi=admin.codice_sdi,
        logo_url=admin.logo_url,
        parent_id=admin.id,
        credit=0
    )

    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    return {
        "message": "Collaboratore admin_team creato con successo.",
        "user_id": new_user.id,
        "email": new_user.email
    }

@router.post("/dealer-team", tags=["Users"])
def create_dealer_team(
    user_data: DealerTeamCreateRequest,
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    Authorize.jwt_required()
    dealer_email = Authorize.get_jwt_subject()
    dealer = db.query(User).filter(User.email == dealer_email).first()

    if not dealer or dealer.role != "dealer":
        raise HTTPException(status_code=403, detail="Accesso negato")

    if db.query(User).filter(User.email == user_data.email).first():
        raise HTTPException(status_code=400, detail="Email già in uso")

    hashed_password = pwd_context.hash(user_data.password)

    new_user = User(
        email=user_data.email,
        hashed_password=hashed_password,
        role="dealer_team",
        nome=user_data.nome,
        cognome=user_data.cognome,
        cellulare=user_data.cellulare,
        indirizzo=dealer.indirizzo,
        cap=dealer.cap,
        citta=dealer.citta,
        ragione_sociale=dealer.ragione_sociale,
        partita_iva=dealer.partita_iva,
        codice_sdi=dealer.codice_sdi,
        logo_url=dealer.logo_url,
        parent_id=dealer.id,
        credit=0
    )

    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    return {
        "message": "Dealer team creato con successo.",
        "user_id": new_user.id,
        "email": new_user.email
    }

@router.get("/mio-team", tags=["Users"])
async def get_mio_team(
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()
    user = db.query(User).filter(User.email == user_email).first()

    if not user:
        raise HTTPException(status_code=401, detail="Utente non trovato")

    if is_admin_user(user):
        admin_id = get_admin_id(user)
        membri = db.query(User).filter(
            User.role == "admin_team",
            User.parent_id == admin_id
        ).all()

    elif is_dealer_user(user):
        dealer_id = get_dealer_id(user)
        membri = db.query(User).filter(
            User.role == "dealer_team",
            User.parent_id == dealer_id
        ).all()

    else:
        membri = []

    risultato = [{
        "id": m.id,
        "nome_completo": f"{m.nome} {m.cognome}".strip(),
        "email": m.email,
        "ragione_sociale": m.ragione_sociale,
        "partita_iva": m.partita_iva,
        "indirizzo": m.indirizzo,
        "cap": m.cap,
        "citta": m.citta,
        "codice_sdi": m.codice_sdi,
        "cellulare": m.cellulare,
        "logo_url": m.logo_url
    } for m in membri]

    return {
        "success": True,
        "colleghi": risultato
    }

@router.put("/team/{id_membro}", tags=["Users"])
def update_team_member(
    id_membro: int,
    member_data: TeamMemberUpdateRequest,
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    # Verifica autenticazione
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()
    current_user = db.query(User).filter(User.email == user_email).first()

    if not current_user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Utente non autorizzato")

    # Trova il membro da aggiornare
    member_to_update = db.query(User).filter(User.id == id_membro).first()

    if not member_to_update:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Membro non trovato")

    # Verifica permessi:
    if current_user.role == "superadmin":
        # Superadmin può aggiornare chiunque
        pass

    elif current_user.role == "admin":
        if not (member_to_update.role == "admin_team" and member_to_update.parent_id == current_user.id):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Operazione non consentita")

    elif current_user.role == "dealer":
        if not (member_to_update.role == "dealer_team" and member_to_update.parent_id == current_user.id):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Operazione non consentita")

    else:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Ruolo non autorizzato")

    # Controlla se l'email è già in uso da un altro utente
    email_exists = db.query(User).filter(User.email == member_data.email, User.id != id_membro).first()
    if email_exists:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email già utilizzata")

    # Aggiorna i dati
    member_to_update.email = member_data.email
    member_to_update.nome = member_data.nome
    member_to_update.cognome = member_data.cognome
    member_to_update.cellulare = member_data.cellulare

    db.commit()
    db.refresh(member_to_update)

    return {
        "message": "Membro del team aggiornato con successo",
        "user": {
            "id": member_to_update.id,
            "email": member_to_update.email,
            "nome": member_to_update.nome,
            "cognome": member_to_update.cognome,
            "cellulare": member_to_update.cellulare
        }
    }

@router.post("/forgot-password")
def forgot_password(email: str, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == email).first()

    if not user:
        raise HTTPException(status_code=404, detail="Utente non trovato")

    token = secrets.token_urlsafe(32)
    expiration = datetime.utcnow() + timedelta(minutes=30)

    user.reset_token = token
    user.reset_token_expiration = expiration
    db.commit()

    # Usa sempre admin_id=1 (SuperAdmin) per il reset password pubblico
    background_tasks.add_task(send_reset_email, 1, email, token)

    return {"message": "Email inviata correttamente"}