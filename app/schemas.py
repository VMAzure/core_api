# schemas.py
from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime

class UserBase(BaseModel):
    email: EmailStr
    nome: str
    cognome: str
    indirizzo: str
    cap: str
    citta: str
    cellulare: str
    ragione_sociale: Optional[str] = None
    partita_iva: Optional[str] = None
    codice_sdi: Optional[str] = None
    credit: Optional[float] = 0.0
    logo_url: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        orm_mode = True

class UserUpdateRequest(BaseModel):
    nome: str
    cognome: str
    indirizzo: str
    cap: str
    citta: str
    cellulare: str

class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str
