from fastapi import APIRouter, HTTPException, Depends, status, Security
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models import User, PurchasedServices, Services, SiteAdminSettings, RefreshToken
from passlib.context import CryptContext
from datetime import datetime, timedelta
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
import os
from dotenv import load_dotenv
from fastapi_jwt_auth import AuthJWT
from pydantic import BaseModel

load_dotenv()

router = APIRouter()

# Configurazione hashing password
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Configurazione JWT
SECRET_KEY = os.getenv("SECRET_KEY", "supersecretkey")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 300
REFRESH_TOKEN_EXPIRE_DAYS = 30


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

@router.post("/login")
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
    Authorize: AuthJWT = Depends()
):
    user = db.query(User).filter(User.email == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenziali non valide")

    # --- SUPERADMIN ---
    if user.role == "superadmin":
        active_services = db.query(Services).filter(Services.page_url.isnot(None)).all()
        active_service_infos = [{"name": s.name, "page_url": s.page_url or "#"} for s in active_services]

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
                    "ragione_sociale": user.ragione_sociale or ""
                },
                "dealer_info": None
            },
            expires_time=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        )

        # --- Refresh token (rotazione singola) ---
        db.query(RefreshToken).filter(RefreshToken.user_id == user.id).delete()
        refresh_token = secrets.token_urlsafe(64)
        expires_at = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
        db.add(RefreshToken(user_id=user.id, token=refresh_token, expires_at=expires_at))
        db.commit()

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer"
        }

    # --- ADMIN / TEAM / DEALER / DEALER_TEAM ---
    if user.role == "admin":
        admin_user = user
        admin_id = user.id
        dealer = None
        dealer_id = None
        active_services = db.query(Services).all()

    elif user.role == "admin_team" and user.parent_id:
        admin_user = db.query(User).filter(User.id == user.parent_id).first()
        if not admin_user or admin_user.role != "admin":
            raise HTTPException(status_code=400, detail="Admin principale non valido")
        admin_id = admin_user.id
        dealer = None
        dealer_id = None
        active_services = db.query(Services).all()

    elif user.role == "dealer":
        dealer = user
        dealer_id = user.id
        admin_user = db.query(User).filter(User.id == user.parent_id).first()
        if not admin_user or admin_user.role != "admin":
            raise HTTPException(status_code=400, detail="Admin non valido")
        admin_id = admin_user.id

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

    # --- Servizi attivi ---
    if user.role in ["admin", "admin_team"]:
        active_services = db.query(Services).all()
    else:
        active_services = db.query(Services).join(
            PurchasedServices, PurchasedServices.service_id == Services.id
        ).filter(
            PurchasedServices.status == "attivo",
            (PurchasedServices.admin_id == admin_id) | (PurchasedServices.dealer_id == dealer_id)
        ).all()

    active_service_infos = [{"name": s.name, "page_url": s.page_url or "#"} for s in active_services]

    # --- Logo / slug ---
    slug = None
    dealer_logo_url = None
    if dealer_id:
        settings = db.query(SiteAdminSettings).filter(SiteAdminSettings.dealer_id == dealer_id).first()
    elif admin_id:
        settings = db.query(SiteAdminSettings).filter(
            SiteAdminSettings.admin_id == admin_id,
            SiteAdminSettings.dealer_id.is_(None)
        ).first()
    if settings:
        dealer_logo_url = settings.logo_web
        slug = settings.slug

    # --- Access token con claims completi ---
    access_token = Authorize.create_access_token(
        subject=user.email,
        user_claims={
            "id": user.id,
            "role": user.role,
            "parent_id": user.parent_id,
            "credit": user.credit,
            "admin_id": admin_id,
            "dealer_id": dealer_id,
            "slug": slug,
            "active_services": active_service_infos,
            "admin_info": {
                "email": admin_user.email,
                "logo_url": admin_user.logo_url or "",
                "ragione_sociale": admin_user.ragione_sociale or ""
            },
            "dealer_info": {
                "id": dealer.id if dealer else None,
                "email": dealer.email if dealer else None,
                "logo_url": dealer_logo_url or "",
                "ragione_sociale": dealer.ragione_sociale if dealer else None
            }
        },
        expires_time=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )

    # --- Refresh token (rotazione singola) ---
    db.query(RefreshToken).filter(RefreshToken.user_id == user.id).delete()
    refresh_token = secrets.token_urlsafe(64)
    expires_at = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    db.add(RefreshToken(user_id=user.id, token=refresh_token, expires_at=expires_at))
    db.commit()

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer"
    }

class RefreshRequest(BaseModel):
    refresh_token: str

@router.post("/refresh")
def refresh(req: RefreshRequest, db: Session = Depends(get_db), Authorize: AuthJWT = Depends()):
    # --- 1. Cerca il refresh token nel DB ---
    rt = db.query(RefreshToken).filter(RefreshToken.token == req.refresh_token).first()
    if not rt or rt.expires_at < datetime.utcnow():
        raise HTTPException(status_code=401, detail="Refresh token non valido o scaduto")

    # --- 2. Recupera l’utente associato ---
    user = db.query(User).filter(User.id == rt.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Utente non trovato")

    # --- 3. Elimina il vecchio refresh token (rotazione singola) ---
    db.delete(rt)

    # --- 4. Ricrea claims come in /login ---
    if user.role == "superadmin":
        admin_user = user
        admin_id = None
        dealer_id = None
        dealer = None
        active_services = db.query(Services).filter(Services.page_url.isnot(None)).all()

    elif user.role == "admin":
        admin_user = user
        admin_id = user.id
        dealer_id = None
        dealer = None
        active_services = db.query(Services).all()

    elif user.role == "admin_team" and user.parent_id:
        admin_user = db.query(User).filter(User.id == user.parent_id).first()
        if not admin_user or admin_user.role != "admin":
            raise HTTPException(status_code=400, detail="Admin principale non valido")
        admin_id = admin_user.id
        dealer_id = None
        dealer = None
        active_services = db.query(Services).all()

    elif user.role == "dealer":
        dealer = user
        dealer_id = user.id
        admin_user = db.query(User).filter(User.id == user.parent_id).first()
        if not admin_user or admin_user.role != "admin":
            raise HTTPException(status_code=400, detail="Admin non valido")
        admin_id = admin_user.id
        active_services = db.query(Services).join(
            PurchasedServices, PurchasedServices.service_id == Services.id
        ).filter(
            PurchasedServices.status == "attivo",
            (PurchasedServices.admin_id == admin_id) | (PurchasedServices.dealer_id == dealer_id)
        ).all()

    elif user.role == "dealer_team" and user.parent_id:
        dealer = db.query(User).filter(User.id == user.parent_id).first()
        if not dealer or dealer.role != "dealer":
            raise HTTPException(status_code=400, detail="Dealer principale non valido")
        dealer_id = dealer.id
        admin_user = db.query(User).filter(User.id == dealer.parent_id).first()
        if not admin_user or admin_user.role != "admin":
            raise HTTPException(status_code=400, detail="Admin non valido")
        admin_id = admin_user.id
        active_services = db.query(Services).join(
            PurchasedServices, PurchasedServices.service_id == Services.id
        ).filter(
            PurchasedServices.status == "attivo",
            (PurchasedServices.admin_id == admin_id) | (PurchasedServices.dealer_id == dealer_id)
        ).all()

    else:
        raise HTTPException(status_code=400, detail="Ruolo utente non valido o relazioni mancanti")

    active_service_infos = [{"name": s.name, "page_url": s.page_url or "#"} for s in active_services]

    # --- 5. Recupero slug e logo ---
    slug = None
    dealer_logo_url = None
    if dealer_id:
        settings = db.query(SiteAdminSettings).filter(SiteAdminSettings.dealer_id == dealer_id).first()
    elif admin_id:
        settings = db.query(SiteAdminSettings).filter(
            SiteAdminSettings.admin_id == admin_id,
            SiteAdminSettings.dealer_id.is_(None)
        ).first()
    if settings:
        dealer_logo_url = settings.logo_web
        slug = settings.slug

    # --- 6. Genera nuovo access token ---
    new_access_token = Authorize.create_access_token(
        subject=user.email,
        user_claims={
            "id": user.id,
            "role": user.role,
            "parent_id": user.parent_id,
            "credit": user.credit,
            "admin_id": admin_id,
            "dealer_id": dealer_id,
            "slug": slug,
            "active_services": active_service_infos,
            "admin_info": {
                "email": admin_user.email if admin_user else None,
                "logo_url": admin_user.logo_url if admin_user else "",
                "ragione_sociale": admin_user.ragione_sociale if admin_user else None
            },
            "dealer_info": {
                "id": dealer.id if dealer else None,
                "email": dealer.email if dealer else None,
                "logo_url": dealer_logo_url or "",
                "ragione_sociale": dealer.ragione_sociale if dealer else None
            }
        },
        expires_time=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )

    # --- 7. Genera nuovo refresh token ---
    new_refresh = secrets.token_urlsafe(64)
    new_expires_at = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    db.add(RefreshToken(user_id=user.id, token=new_refresh, expires_at=new_expires_at))

    db.commit()

    return {
        "access_token": new_access_token,
        "refresh_token": new_refresh,
        "token_type": "bearer"
    }



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

    # --- trova l'admin corretto ---
    if user.role in ["admin", "superadmin"]:
        admin_id = user.id
    else:
        admin_id = user.parent_id  # per dealer/dealer_team/admin_team

    if not admin_id:
        raise HTTPException(status_code=400, detail="Admin non trovato per questo utente")

    background_tasks.add_task(send_reset_email, admin_id, request.email, token)

    return {"message": "Email inviata correttamente"}

class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str

@router.post("/reset-password")
def reset_password(request: ResetPasswordRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(
        User.reset_token == request.token,
        User.reset_token_expiration > datetime.utcnow()
    ).first()

    if not user:
        raise HTTPException(status_code=400, detail="Token non valido o scaduto")

    user.hashed_password = pwd_context.hash(request.new_password)
    user.reset_token = None
    user.reset_token_expiration = None

    db.commit()

    return {"message": "Password aggiornata con successo"}

