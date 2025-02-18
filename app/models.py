from sqlalchemy import Column, Integer, String, Text, Float, DateTime, func
from sqlalchemy.orm import relationship
from datetime import datetime
from passlib.context import CryptContext
from app.database import Base  # Manteniamo solo Base senza importare engine

# Configurazione hashing password
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

class User(Base):
    __tablename__ = "users"
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
    parent_id = Column(Integer, ForeignKey("public.users.id"), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    parent = relationship("User", remote_side=[id], backref="dealers")

    def set_password(self, password: str):
        """Salva la password criptata"""
        self.hashed_password = pwd_context.hash(password)

    def check_password(self, password: str):
        """Verifica la password"""
        return pwd_context.verify(password, self.hashed_password)
        
class Services(Base):
    __tablename__ = "services"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, index=True)
    description = Column(Text, nullable=True)
    price = Column(Float, nullable=False)
    created_at = Column(DateTime, default=func.now())  # ✅ Aggiunto
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())  # ✅ Aggiunto

class PurchasedServices(Base):
    __tablename__ = "purchased_services"

    id = Column(Integer, primary_key=True, index=True)
    admin_id = Column(Integer, ForeignKey("users.id"))
    service_id = Column(Integer, ForeignKey("services.id"))
    status = Column(String, default="attivo")
