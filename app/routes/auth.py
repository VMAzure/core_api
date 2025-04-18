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
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
    Authorize: AuthJWT = Depends()
):
    user = db.query(User).filter(User.email == form_data.username).first()

    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenziali non valide")

    # SUPERADMIN
    if user.role == "superadmin":
        active_services = db.query(Services).filter(Services.page_url.isnot(None)).all()

        active_service_infos = [
            {"name": service.name, "page_url": service.page_url or "#"}
            for service in active_services
        ]

        access_token = Authorize.create_access_token(
            subject=user.email,
            user_claims={
                "id": user.id,
                "role": user.role,
                "parent_id": user.parent_id,
                "credit": user.credit,
                "admin_id": None,
                "dealer_id": None,
                "active_services": active_service_infos,
                "admin_info": {
                    "email": user.email,
                    "logo_url": user.logo_url or "",
                     "ragione_sociale": admin_user.ragione_sociale or ""  
                }
            },
            expires_time=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        )

        return {"access_token": access_token, "token_type": "bearer"}

    # ADMIN
    if user.role == "admin":
        admin_user = user
        admin_id = user.id
        dealer = None
        dealer_id = None

    # ADMIN_TEAM
    elif user.role == "admin_team" and user.parent_id:
        admin_user = db.query(User).filter(User.id == user.parent_id).first()
        if not admin_user or admin_user.role != "admin":
            raise HTTPException(status_code=400, detail="Admin principale non valido")
        admin_id = admin_user.id
        dealer = None
        dealer_id = None

    # DEALER
    elif user.role == "dealer":
        dealer = user
        dealer_id = user.id
        admin_user = db.query(User).filter(User.id == user.parent_id).first()
        if not admin_user or admin_user.role != "admin":
            raise HTTPException(status_code=400, detail="Admin non valido")
        admin_id = admin_user.id

    # DEALER_TEAM
    elif user.role == "dealer_team" and user.parent_id:
        dealer = db.query(User).filter(User.id == user.parent_id).first()
        if not dealer or dealer.role != "dealer":
            raise HTTPException(status_code=400, detail="Dealer principale non valido")
        dealer_id = dealer.id
        admin_user = db.query(User).filter(User.id == dealer.parent_id).first()
        if not admin_user or admin_user.role != "admin":
            raise HTTPException(status_code=400, detail="Admin non valido")
        admin_id = admin_user.id

    else:
        raise HTTPException(status_code=400, detail="Ruolo utente non valido o relazioni mancanti")

    # Recupera servizi attivi dell’admin
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
        "id": user.id,
        "role": user.role,
        "parent_id": user.parent_id,
        "credit": user.credit,
        "admin_id": admin_id,
        "dealer_id": dealer_id,
        "active_services": active_service_infos,
        "admin_info": {
            "email": admin_user.email,
            "logo_url": admin_user.logo_url or "",
            "ragione_sociale": admin_user.ragione_sociale or ""  
        }
    },
    expires_time=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
)


    return {"access_token": access_token, "token_type": "bearer"}





@router.post('/refresh-token')
def refresh_token(Authorize: AuthJWT = Depends(), db: Session = Depends(get_db)):
    Authorize.jwt_required()

    current_user_email = Authorize.get_jwt_subject()

    user = db.query(User).filter(User.email == current_user_email).first()
    if not user:
        raise HTTPException(status_code=404, detail="Utente non trovato")

    admin_user = None
    admin_id = None
    dealer = None
    dealer_id = None

    if user.role == "superadmin":
        admin_user = user
        admin_id = None
        dealer_id = None

        active_services = db.query(Services).filter(Services.page_url.isnot(None)).all()

    elif user.role == "admin":
        admin_user = user
        admin_id = user.id

    elif user.role == "admin_team" and user.parent_id:
        admin_user = db.query(User).filter(User.id == user.parent_id).first()
        admin_id = admin_user.id if admin_user else None

    elif user.role == "dealer":
        dealer = user
        dealer_id = user.id
        admin_user = db.query(User).filter(User.id == user.parent_id).first()
        admin_id = admin_user.id if admin_user else None

    elif user.role == "dealer_team" and user.parent_id:
        dealer = db.query(User).filter(User.id == user.parent_id).first()
        dealer_id = dealer.id if dealer else None
        admin_user = db.query(User).filter(User.id == dealer.parent_id).first() if dealer else None
        admin_id = admin_user.id if admin_user else None

    else:
        raise HTTPException(status_code=400, detail="Ruolo utente non valido o relazioni mancanti")

    if user.role != "superadmin":
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

    new_token = Authorize.create_access_token(
        subject=current_user_email,
        user_claims={
            "id": user.id,
            "role": user.role,
            "parent_id": user.parent_id,
            "credit": user.credit,
            "admin_id": admin_id,
            "dealer_id": dealer_id,
            "active_services": active_service_infos,
            "admin_info": {
                "email": admin_user.email if admin_user else None,
                "logo_url": admin_user.logo_url if admin_user and admin_user.logo_url else ""
            }
        },
        expires_time=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )

    return {"access_token": new_token}

from pydantic import BaseModel
from fastapi import BackgroundTasks, Depends, APIRouter, HTTPException
import secrets  # ✅ mancava questo import!
from app.utils.email import send_reset_email  # ✅ mancava questo import!


class ForgotPasswordRequest(BaseModel):
    email: str

@router.post("/forgot-password")
def forgot_password(request: ForgotPasswordRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == request.email).first()

    if not user:
        raise HTTPException(status_code=404, detail="Utente non trovato")

    token = secrets.token_urlsafe(32)
    expiration = datetime.utcnow() + timedelta(minutes=30)

    user.reset_token = token
    user.reset_token_expiration = expiration
    db.commit()

    # Usa sempre admin_id=1 (SuperAdmin)
    background_tasks.add_task(send_reset_email, 4, request.email, token)

    return {"message": "Email inviata correttamente"}
