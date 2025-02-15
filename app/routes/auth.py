from fastapi import APIRouter, HTTPException, Depends, status, Security
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models import User
from passlib.context import CryptContext
from datetime import datetime, timedelta
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
import os
from dotenv import load_dotenv

# Carica le variabili dal file .env
load_dotenv()

router = APIRouter()

# Configurazione hashing password
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Configurazione JWT
SECRET_KEY = os.getenv("SECRET_KEY", "supersecretkey")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

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

# Funzione per creare un token JWT con ruolo e credito
def create_access_token(data: dict, expires_delta: timedelta = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta if expires_delta else timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

# Funzione per ottenere l'utente corrente dal token JWT

def get_current_user(token: str = Security(oauth2_scheme), db: Session = Depends(get_db)):
    if token is None:
        raise HTTPException(status_code=401, detail="Token JWT mancante")

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        print(f"🔍 DEBUG: Token decodificato - {payload}")  # Aggiungiamo un debug
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token JWT scaduto")
    except jwt.JWTError:
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
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    print(f"🔍 DEBUG: Tentativo di login con username={form_data.username}, password={form_data.password}")

    user = db.query(User).filter(User.email == form_data.username).first()
    
    if not user:
        print("❌ DEBUG: Utente non trovato!")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenziali non valide")
    
    if not verify_password(form_data.password, user.hashed_password):
        print("❌ DEBUG: Password errata!")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenziali non valide")
    
    print(f"✅ DEBUG: Utente autenticato: {user.email}, ruolo: {user.role}, credito: {user.credit}")

    access_token = create_access_token(data={"sub": user.email, "role": user.role, "credit": user.credit})
    
    print(f"🔑 DEBUG: Token generato: {access_token}")
    
    return {"access_token": access_token, "token_type": "bearer"}


