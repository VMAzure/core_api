# schemas.py
from pydantic import BaseModel, EmailStr, root_validator 
from typing import Optional
from datetime import datetime, date
from pydantic import BaseModel, EmailStr, Field
import uuid
from uuid import UUID


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
    token: str  # 👈✅ AGGIUNGI QUESTO CAMPO (obbligatorio!)
    tipo_cliente: str
    nome: Optional[str] = None
    cognome: Optional[str] = None
    ragione_sociale: Optional[str] = None
    codice_fiscale: Optional[str] = None
    partita_iva: Optional[str] = None
    indirizzo: str
    telefono: str
    email: EmailStr
    iban: Optional[str] = None
    dealer_id: Optional[int] = None





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

# Schema per impostazioni sito admin
class SiteAdminSettingsSchema(BaseModel):
    admin_id: int
    primary_color: Optional[str]
    secondary_color: Optional[str]
    tertiary_color: Optional[str]
    font_family: Optional[str]
    favicon_url: Optional[str]
    custom_css: Optional[str]
    custom_js: Optional[str]
    dark_mode_enabled: Optional[bool]
    menu_style: Optional[str]
    footer_text: Optional[str]

    class Config:
        orm_mode = True

# Schema per configurazione SEO pagine sito
class SitePageSchema(BaseModel):
    admin_id: int
    page_name: str
    page_url: str
    is_active: Optional[bool] = True
    sort_order: Optional[int] = 0
    parent_page_id: Optional[int] = None
    seo_title: Optional[str] = None
    seo_description: Optional[str] = None
    seo_keywords: Optional[str] = None
    meta_robots: Optional[str] = "index, follow"
    canonical_url: Optional[str] = None
    json_ld_schema: Optional[str] = None

    class Config:
        orm_mode = True


class AutoUsataCreate(BaseModel):
    targa: str
    anno_immatricolazione: int
    data_passaggio_proprieta: Optional[date]
    km_certificati: int
    data_ultimo_intervento: Optional[date]
    descrizione_ultimo_intervento: Optional[str]
    cronologia_tagliandi: bool
    doppie_chiavi: bool
    codice_motornet: str
    colore: Optional[str]
    prezzo_costo: float
    prezzo_vendita: float

    
class AdminTeamCreateRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    nome: str
    cognome: str
    cellulare: str

class DealerTeamCreateRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    nome: str
    cognome: str
    cellulare: str


class ClienteConsensoRequest(BaseModel):
    privacy: bool
    newsletter: Optional[bool] = False
    marketing: Optional[bool] = False
    ip: Optional[str] = None
    note: Optional[str] = None
    attivo: Optional[bool] = True  # 👈 aggiunto

class ClienteConsensoResponse(ClienteConsensoRequest):
    id: uuid.UUID
    cliente_id: int
    data_consenso: datetime
    attivo: bool  # 👈 aggiunto

    class Config:
        orm_mode = True


class NltClientiPubbliciBase(BaseModel):
    email: str
    dealer_slug: str

class NltClientiPubbliciCreate(NltClientiPubbliciBase):
    slug_offerta: Optional[str] = None
    anticipo: Optional[float] = None
    canone: Optional[float] = None
    durata: Optional[int] = None
    km: Optional[int] = None

class NltClientiPubbliciResponse(NltClientiPubbliciBase):
    id: UUID
    token: str
    cliente_id: Optional[int]
    data_creazione: datetime
    data_scadenza: datetime
    confermato: bool
    slug_offerta: Optional[str] = None
    anticipo: Optional[float] = None
    canone: Optional[float] = None
    durata: Optional[int] = None
    km: Optional[int] = None
    stato: Optional[str]

    class Config:
        orm_mode = True

