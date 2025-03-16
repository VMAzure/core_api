from sqlalchemy import Column, Integer, String, Text, Float, DateTime, ForeignKey, func, Boolean
from sqlalchemy.orm import relationship
from datetime import datetime
from passlib.context import CryptContext
from app.database import Base  # Manteniamo solo Base senza importare engine
from typing import TYPE_CHECKING, Optional
from pydantic import BaseModel, EmailStr
from sqlalchemy.dialects.postgresql import UUID, JSONB
import uuid



if TYPE_CHECKING:
    from app.models import AssignedServices
# Configurazione hashing password
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

class Services(Base):
    __tablename__ = "services"
    __table_args__ = {"schema": "public"}
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, index=True)
    description = Column(Text, nullable=True)
    price = Column(Float, nullable=False)
    image_url = Column(Text, nullable=True)
    page_url = Column(String, nullable=True)  # ✅ Aggiunto il campo per la pagina del servizio
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # ✅ RIMOSSO il `back_populates="purchased_services"`

class User(Base):
    __tablename__ = "utenti"
    __table_args__ = {"schema": "public"}

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    role = Column(String(50), nullable=False)

    nome = Column(String(255))
    cognome = Column(String(255))
    credit = Column(Float, default=0.0)
    parent_id = Column(Integer, ForeignKey("public.utenti.id"))
    indirizzo = Column(String)
    cap = Column(String)
    citta = Column(String)
    cellulare = Column(String)
    ragione_sociale = Column(String, nullable=True)
    codice_sdi = Column(String, nullable=True)
    credit = Column(Float, default=0.0)
    
    smtp_settings = relationship(
        "SmtpSettings",
        uselist=False,
        back_populates="admin",
        cascade="all, delete-orphan"
    )

    parent_id = Column(Integer, ForeignKey("public.utenti.id"), nullable=True)
    parent = relationship(
        "User",
        remote_side=[id],
        backref="dealers",
        primaryjoin="User.parent_id == User.id"
    )

    def set_password(self, password: str):
        self.hashed_password = pwd_context.hash(password)

    def check_password(self, password: str):
        return pwd_context.verify(password, self.hashed_password)


        
class PurchasedServices(Base):
    __tablename__ = "purchased_services"
    __table_args__ = {"schema": "public"}

    id = Column(Integer, primary_key=True, index=True)
    admin_id = Column(Integer, ForeignKey("public.utenti.id"), nullable=False)
    service_id = Column(Integer, ForeignKey("public.services.id"), nullable=False)
    status = Column(String, default="attivo")
    activated_at = Column(DateTime, default=func.now())

    admin = relationship("User", backref="purchased_services")  
    service = relationship("Services", backref="purchased_services")  # ✅ Modificato da back_populates a backref

class CreditTransaction(Base):
    __tablename__ = "credit_transactions"
    __table_args__ = {"schema": "public"}  # ✅ Aggiunto

    id = Column(Integer, primary_key=True, index=True)
    admin_id = Column(Integer, ForeignKey("public.utenti.id"), nullable=False)  # ✅ Modificato
    amount = Column(Float, nullable=False)
    transaction_type = Column(String, nullable=False)
    created_at = Column(DateTime, default=func.now())

# ✅ Modello AssignedServices
class AssignedServices(Base):
    __tablename__ = "assigned_services"
    __table_args__ = {"schema": "public"}  # ✅ Assicura che sia nello schema corretto

    id = Column(Integer, primary_key=True, index=True)
    admin_id = Column(Integer, ForeignKey("public.utenti.id"), nullable=True)
    dealer_id = Column(Integer, ForeignKey("public.utenti.id"), nullable=True)
    service_id = Column(Integer, ForeignKey("public.services.id"), nullable=True)  # ✅ AGGIUNTO SCHEMA "public."

    status = Column(String, nullable=True, default="attivo")
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relazioni
    service = relationship("Services", backref="assigned_services")  # ✅ Manteniamo `backref`
    dealer = relationship("User", foreign_keys=[dealer_id])
    admin = relationship("User", foreign_keys=[admin_id])


class ClienteModifica(Base):
    __tablename__ = "clienti_modifiche"
    __table_args__ = {"schema": "public"}  # <-- Aggiungi questa riga!

    id = Column(Integer, primary_key=True, index=True)
    cliente_id = Column(Integer, ForeignKey("public.clienti.id"))  # <-- aggiungi public.
    richiesto_da = Column(Integer, ForeignKey("public.utenti.id"))
    approvato_da = Column(Integer, ForeignKey("public.utenti.id"), nullable=True)
    campo_modificato = Column(String(255))
    valore_vecchio = Column(Text)
    valore_nuovo = Column(Text)
    messaggio = Column(Text)
    stato = Column(String(50), default="In attesa")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Cliente(Base):
    __tablename__ = "clienti"
    __table_args__ = {"schema": "public"}

    id = Column(Integer, primary_key=True, index=True)
    admin_id = Column(Integer, ForeignKey("public.utenti.id"), nullable=False)
    dealer_id = Column(Integer, ForeignKey("public.utenti.id"), nullable=True)
    
    tipo_cliente = Column(String, nullable=False)
    nome = Column(String, nullable=True)
    cognome = Column(String, nullable=True)
    ragione_sociale = Column(String, nullable=True)
    codice_fiscale = Column(String, nullable=True)
    partita_iva = Column(String, nullable=True)
    indirizzo = Column(String, nullable=True)
    telefono = Column(String, nullable=True)
    email = Column(String, nullable=True)
    iban = Column(String, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    admin = relationship("User", foreign_keys=[admin_id])
    dealer = relationship("User", foreign_keys=[dealer_id])

class NltService(Base):
    __tablename__ = "nlt_services"
    __table_args__ = {"schema": "public"}


    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(150), nullable=False)
    description = Column(String)
    conditions = Column(JSONB)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

class NltDocumentiRichiesti(Base):
    __tablename__ = "nlt_documenti_richiesti"

    id = Column(Integer, primary_key=True, index=True)
    tipo_cliente = Column(String(50), nullable=False, index=True)
    documento = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class NltPreventivi(Base):
    __tablename__ = "nlt_preventivi"
    __table_args__ = {"schema": "public"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cliente_id = Column(Integer, ForeignKey("public.clienti.id"), nullable=True)
    file_url = Column(Text, nullable=False)
    creato_da = Column(Integer, ForeignKey("public.utenti.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # ✅ Aggiunti i nuovi campi
    marca = Column(Text, nullable=True)
    modello = Column(Text, nullable=True)
    durata = Column(Integer, nullable=True)
    km_totali = Column(Integer, nullable=True)
    anticipo = Column(Float, nullable=True)
    canone = Column(Float, nullable=True)
    visibile = Column(Integer, default=1)  # 👈 Aggiunto campo visibile


    # Relazioni utili (opzionali)
    cliente = relationship("Cliente")
    creatore = relationship("User", foreign_keys=[creato_da])

class SmtpSettings(Base):
    __tablename__ = "smtp_settings"

    id = Column(Integer, primary_key=True, index=True)
    admin_id = Column(Integer, ForeignKey('utenti.id', ondelete='CASCADE'), nullable=False)
    smtp_host = Column(String(255), nullable=False)
    smtp_port = Column(Integer, nullable=False)
    smtp_user = Column(String(255), nullable=False)
    smtp_password = Column(String(255), nullable=False)
    use_ssl = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    admin = relationship("User", back_populates="smtp_settings")

