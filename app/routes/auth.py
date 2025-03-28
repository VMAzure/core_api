from fastapi import APIRouter, HTTPException, Depends, status, Security
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models import User, PurchasedServices, Services
from passlib.context import CryptContext
from datetime import datetime, timedelta
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
import os
from dotenv import load_dotenv
from fastapi_jwt_auth import AuthJWT


# Carica le variabili dal file .env
load_dotenv()

router = APIRouter()

# Configurazione hashing password
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Configurazione JWT
SECRET_KEY = os.getenv("SECRET_KEY", "supersecretkey")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 300


# OAuth2 per gestione token
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login", auto_error=False)

# Funzione per ottenere il DB
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Funzione per verificare la password
def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)


# Funzione per ottenere l'utente corrente dal token JWT

def get_current_user(token: str = Security(oauth2_scheme), db: Session = Depends(get_db)):
    print(f"🔍 DEBUG: Token ricevuto: {token}")
    
    if token is None:
        raise HTTPException(status_code=401, detail="Token JWT mancante")

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        print(f"🔍 DEBUG: Token decodificato: {payload}")  # 🔹 Stampa il payload ricevuto
    except jwt.ExpiredSignatureError:
        print("❌ DEBUG: Token JWT scaduto")
        raise HTTPException(status_code=401, detail="Token JWT scaduto")
    except jwt.JWTError as e:
        print(f"❌ DEBUG: Errore nella decodifica del token: {e}")
        raise HTTPException(status_code=401, detail="Token JWT non valido")

    user_email = payload.get("sub")
    if user_email is None:
        raise HTTPException(status_code=401, detail="Token JWT non contiene il campo 'sub'")

    user = db.query(User).filter(User.email == user_email).first()
    if user is None:
        raise HTTPException(status_code=401, detail="Utente non trovato")

    return {"user": user, "role": user.role, "credit": user.credit}

# Endpoint di login
@router.post("/login")
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db), Authorize: AuthJWT = Depends()):
    user = db.query(User).filter(User.email == form_data.username).first()
    
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenziali non valide")

    if user.role == "admin":
        admin_id = user.id
        admin_user = user
    elif user.role == "dealer" and user.parent_id:
        admin_id = user.parent_id
        admin_user = db.query(User).filter(User.id == admin_id).first()
    else:
        raise HTTPException(status_code=400, detail="Ruolo utente non valido o admin non assegnato")

    active_services = db.query(Services).join(
        PurchasedServices, PurchasedServices.service_id == Services.id
    ).filter(
        PurchasedServices.admin_id == admin_id,
        PurchasedServices.status == "active"
    ).all()

    active_service_infos = [
        {"name": service.name, "page_url": service.page_url or "#"}
        for service in active_services
    ]

    access_token = Authorize.create_access_token(
        subject=user.email,
        user_claims={
            "role": user.role,
            "credit": user.credit,
            "active_services": active_service_infos,
            "admin_info": {
                "email": admin_user.email,
                "logo_url": admin_user.logo_url or ""
            }
        },
        expires_time=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )

    return {"access_token": access_token, "token_type": "bearer"}



@router.post('/refresh-token')
def refresh_token(Authorize: AuthJWT = Depends(), db: Session = Depends(get_db)):
    Authorize.jwt_required()  # verifica token attuale

    current_user_email = Authorize.get_jwt_subject()

    # Recupera nuovamente l'utente
    user = db.query(User).filter(User.email == current_user_email).first()

    if not user:
        raise HTTPException(status_code=404, detail="Utente non trovato")

    # Recupera i servizi attivi aggiornati
    active_services = db.query(Services).join(
        PurchasedServices, PurchasedServices.service_id == Services.id
    ).filter(
        PurchasedServices.admin_id == user.id,
        PurchasedServices.status == "active"
    ).all()

    active_service_infos = [
        {
            "name": service.name,
            "page_url": service.page_url or "#"
        }
        for service in active_services
    ]

    # Genera nuovo token JWT aggiornato
    new_token = Authorize.create_access_token(
        subject=current_user_email,
        user_claims={
            "role": user.role,
            "credit": user.credit,
            "active_services": active_service_names
        },
        expires_time=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )

    return {"access_token": new_token}