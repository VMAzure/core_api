from sqlalchemy import Column, Integer, String, Text, Float, DateTime, ForeignKey, func
from sqlalchemy.orm import relationship
from datetime import datetime
from passlib.context import CryptContext
from app.database import Base  # Manteniamo solo Base senza importare engine

# Configurazione hashing password
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

class User(Base):
    __tablename__ = "utenti"
    __table_args__ = {"schema": "public"}  # Forziamo lo schema "public"

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

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    parent = relationship("User", remote_side=[id], backref="dealers", primaryjoin="User.parent_id == User.id")


    def set_password(self, password: str):
        """Salva la password criptata"""
        self.hashed_password = pwd_context.hash(password)

    def check_password(self, password: str):
        """Verifica la password"""
        return pwd_context.verify(password, self.hashed_password)
        
class Services(Base):
    __tablename__ = "services"
    __table_args__ = {"schema": "public"}  # ✅ Aggiunto per uniformità

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, index=True)
    description = Column(Text, nullable=True)
    price = Column(Float, nullable=False)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # ✅ Aggiunto il back_populates per il collegamento con PurchasedServices
    purchased_services = relationship("PurchasedServices", back_populates="service")


class PurchasedServices(Base):
    __tablename__ = "purchased_services"
    __table_args__ = {"schema": "public"}  # ✅ Aggiunto per rispettare lo schema

    id = Column(Integer, primary_key=True, index=True)
    admin_id = Column(Integer, ForeignKey("public.utenti.id"), nullable=False)  # ✅ Modificato
    service_id = Column(Integer, ForeignKey("public.services.id"), nullable=False)  # ✅ Modificato
    status = Column(String, default="attivo")
    activated_at = Column(DateTime, default=func.now())

    admin = relationship("User", backref="purchased_services")
    service = relationship("Services", backref="purchased_services")


class CreditTransaction(Base):
    __tablename__ = "credit_transactions"
    __table_args__ = {"schema": "public"}  # ✅ Aggiunto

    id = Column(Integer, primary_key=True, index=True)
    admin_id = Column(Integer, ForeignKey("public.utenti.id"), nullable=False)  # ✅ Modificato
    amount = Column(Float, nullable=False)
    transaction_type = Column(String, nullable=False)
    created_at = Column(DateTime, default=func.now())

