from pydantic import BaseModel, Field, EmailStr
from typing import Optional, List
from datetime import datetime, date
import uuid

# Compagnie
class CompagniaBase(BaseModel):
    nome: str
    indirizzo: Optional[str]
    telefono: Optional[str]
    email: Optional[EmailStr]
    sito_web: Optional[str]

    class Config:
        orm_mode = True

class CompagniaResponse(CompagniaBase):
    id: int

# Agenzie
class AgenziaBase(BaseModel):
    nome: str
    indirizzo: Optional[str]
    telefono: Optional[str]
    email: Optional[EmailStr]

    class Config:
        orm_mode = True

class AgenziaResponse(AgenziaBase):
    id: int

# Prodotti
class ProdottoBase(BaseModel):
    compagnia_id: int
    ramo_id: int
    nome: str
    descrizione: Optional[str]

    class Config:
        orm_mode = True

class ProdottoResponse(ProdottoBase):
    id: int

# Garanzie
class GaranziaBase(BaseModel):
    nome: str
    descrizione: Optional[str]

    class Config:
        orm_mode = True

class GaranziaResponse(GaranziaBase):
    id: int

# Massimali e Franchigie
class MassimaleFranchigiaBase(BaseModel):
    nome: str
    valore: float

    class Config:
        orm_mode = True

class MassimaleFranchigiaResponse(MassimaleFranchigiaBase):
    id: int

# Preventivi (garanzie e rischi)
class PreventivoGaranzia(BaseModel):
    garanzia_id: int
    massimali_franchigie: List[int] = []

    class Config:
        orm_mode = True

class PreventivoRischio(BaseModel):
    descrizione: str

    class Config:
        orm_mode = True

# Preventivi (input)
class PreventivoCreate(BaseModel):
    cliente_id: int
    prodotto_id: int
    stato_id: int
    frazionamento_id: int
    premio_totale: float
    garanzie: List[PreventivoGaranzia]
    rischi: Optional[List[PreventivoRischio]]

    class Config:
        orm_mode = True

# Preventivi (output)
class PreventivoResponse(BaseModel):
    id: uuid.UUID
    id_cliente: int
    id_prodotto: uuid.UUID
    id_agenzia: uuid.UUID
    id_compagnia: uuid.UUID
    id_ramo: uuid.UUID
    id_frazionamento: uuid.UUID
    premio_rata: float
    premio_competenza: float
    id_admin: Optional[int]
    id_team: Optional[int]
    data_creazione: datetime
    modalita_pagamento_cliente: Optional[uuid.UUID]
    confermato_da_cliente: bool
    data_scadenza_validita: Optional[date]
    data_accettazione_cliente: Optional[datetime]
    blob_url: Optional[str]
    stato: Optional[str]


    class Config:
        orm_mode = True

# Conferma preventivo
class ConfermaPreventivo(BaseModel):
    preventivo_id: uuid.UUID
    ip_cliente: str
    confermato: bool
    note: Optional[str]

    class Config:
        orm_mode = True

# Polizza (input)
class PolizzaCreate(BaseModel):
    preventivo_id: uuid.UUID
    numero_polizza: str
    data_decorrenza: date

    class Config:
        orm_mode = True

# Polizza (output)
class PolizzaResponse(BaseModel):
    id: uuid.UUID
    preventivo_id: uuid.UUID
    numero_polizza: str
    data_decorrenza: date
    data_emissione: datetime

    class Config:
        orm_mode = True

# Incasso (input)
class IncassoCreate(BaseModel):
    polizza_id: uuid.UUID
    importo: float
    metodo_pagamento: Optional[str]

    class Config:
        orm_mode = True

# Incasso (output)
class IncassoResponse(BaseModel):
    id: uuid.UUID
    polizza_id: uuid.UUID
    importo: float
    metodo_pagamento: Optional[str]
    data_incasso: datetime

    class Config:
        orm_mode = True
