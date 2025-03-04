# schemas.py
from pydantic import BaseModel, EmailStr, root_validator 
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



class ClienteCreateRequest(BaseModel):
    tipo_cliente: str
    nome: Optional[str] = None
    cognome: Optional[str] = None
    ragione_sociale: Optional[str] = None
    codice_fiscale: Optional[str] = None  # ✅ Ora opzionale
    partita_iva: Optional[str] = None
    indirizzo: str
    telefono: str
    email: EmailStr
    iban: Optional[str] = None




class ClienteResponse(BaseModel):
    id: int
    admin_id: int
    dealer_id: Optional[int] = None
    tipo_cliente: str
    nome: Optional[str] = None
    cognome: Optional[str] = None
    ragione_sociale: Optional[str] = None
    codice_fiscale: Optional[str] = None
    partita_iva: Optional[str] = None
    indirizzo: str
    telefono: str
    email: str
    iban: Optional[str] = None

    @root_validator
    def validate_codici(cls, values):
        cf, piva = values.get('codice_fiscale'), values.get('partita_iva')
        if not cf and not piva:
            raise ValueError('Almeno uno tra Codice Fiscale e Partita IVA deve essere presente.')
        return values

    class Config:
        orm_mode = True
