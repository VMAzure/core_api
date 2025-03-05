from sqlalchemy import Column, Integer, String, Text, Float, DateTime, ForeignKey, func
from sqlalchemy.orm import relationship
from datetime import datetime
from passlib.context import CryptContext
from app.database import Base  # Manteniamo solo Base senza importare engine
from typing import TYPE_CHECKING, Optional
from pydantic import BaseModel, EmailStr
from .database import Base


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
    role = Column(String, nullable=False)

    nome = Column(String, nullable=False)
    cognome = Column(String, nullable=False)
    ragione_sociale = Column(String, nullable=True)
    partita_iva = Column(String, unique=True, nullable=True)
    indirizzo = Column(String, nullable=False)
    cap = Column(String, nullable=False)
    citta = Column(String, nullable=False)
    codice_sdi = Column(String, nullable=True)
    cellulare = Column(String, nullable=False)

    credit = Column(Float, default=0.0)
    parent_id = Column(Integer, ForeignKey("public.utenti.id"), nullable=True)
    logo_url = Column(String, nullable=True)  # ✅ aggiunta

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    parent = relationship("User", remote_side=[id], backref="dealers", primaryjoin="User.parent_id == User.id")

    def set_password(self, password: str):
        """Salva la password criptata"""
        self.hashed_password = pwd_context.hash(password)

    def check_password(self, password: str):
        """Verifica la password"""
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


class Cliente(Base):
    __tablename__ = "clienti"
    __table_args__ = {"schema": "public"}

    id = Column(Integer, primary_key=True, index=True)
    admin_id = Column(Integer, ForeignKey("public.utenti.id"), nullable=False)
    dealer_id = Column(Integer, ForeignKey("public.utenti.id"), nullable=True)

    tipo_cliente = Column(String(20), nullable=False)
    nome = Column(String(100))
    cognome = Column(String(100))
    ragione_sociale = Column(String(150))
    codice_fiscale = Column(String(16))
    partita_iva = Column(String(15))
    indirizzo = Column(String(255))
    telefono = Column(String(20))
    email = Column(String(150), nullable=False)
    iban = Column(String(34))

    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    admin = relationship("User", foreign_keys=[admin_id])
    dealer = relationship("User", foreign_keys=[dealer_id])

class ClienteModifica(Base):
    __tablename__ = "clienti_modifiche"

    id = Column(Integer, primary_key=True, index=True)
    cliente_id = Column(Integer, ForeignKey("clienti.id"), nullable=False)
    richiesto_da = Column(Integer, ForeignKey("utenti.id"), nullable=False)
    campo_modificato = Column(String(50), nullable=False)
    valore_vecchio = Column(String(255), nullable=True)
    valore_nuovo = Column(String(255), nullable=False)
    messaggio = Column(Text, nullable=True)
    stato = Column(String(20), default="In attesa")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)