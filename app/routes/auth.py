from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models import User
from passlib.context import CryptContext
from datetime import datetime, timedelta
import jwt
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

# Funzione per creare un token JWT
def create_access_token(data: dict, expires_delta: timedelta = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta if expires_delta else timedelta(minutes=15))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

# Endpoint di login
@router.post("/login")
def login(email: str, password: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == email).first()
    
    if not user or not verify_password(password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    access_token = create_access_token(data={"sub": user.email, "role": user.role})
    
    return {"access_token": access_token, "token_type": "bearer"}
