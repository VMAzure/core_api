from sqlalchemy import Column, String, Integer, ForeignKey, DateTime, Numeric, Boolean, Text, Date, func
from sqlalchemy.orm import relationship
from app.database import Base
import uuid
from sqlalchemy.dialects.postgresql import UUID


# Modelli SQLAlchemy per Azinsurance (prefisso: ass_)

class AssCompagnia(Base):
    __tablename__ = "ass_compagnie"
    __table_args__ = {'schema': 'public'}

    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String(150), nullable=False, unique=True)
    indirizzo = Column(String(255))
    telefono = Column(String(20))
    email = Column(String(100))
    sito_web = Column(String(100))


class AssAgenzia(Base):
    __tablename__ = "ass_agenzie"
    __table_args__ = {'schema': 'public'}

    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String(150), nullable=False, unique=True)
    indirizzo = Column(String(255))
    telefono = Column(String(20))
    email = Column(String(100))


class AssAgenziaCompagnia(Base):
    __tablename__ = "ass_agenzie_compagnie"
    __table_args__ = {'schema': 'public'}

    id = Column(Integer, primary_key=True, index=True)
    agenzia_id = Column(Integer, ForeignKey("public.ass_agenzie.id"), nullable=False)
    compagnia_id = Column(Integer, ForeignKey("public.ass_compagnie.id"), nullable=False)


class AssRamo(Base):
    __tablename__ = "ass_ramo"
    __table_args__ = {'schema': 'public'}

    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String(150), nullable=False, unique=True)


class AssStatoPolizza(Base):
    __tablename__ = "ass_stato_polizza"
    __table_args__ = {'schema': 'public'}

    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String(50), nullable=False, unique=True)


class AssFrazionamento(Base):
    __tablename__ = "ass_frazionamento"
    __table_args__ = {'schema': 'public'}

    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String(50), nullable=False, unique=True)
    mesi = Column(Integer, nullable=False)


class AssProdotto(Base):
    __tablename__ = "ass_prodotti"
    __table_args__ = {'schema': 'public'}

    id = Column(Integer, primary_key=True, index=True)
    compagnia_id = Column(Integer, ForeignKey("public.ass_compagnie.id"), nullable=False)
    ramo_id = Column(Integer, ForeignKey("public.ass_ramo.id"), nullable=False)
    nome = Column(String(150), nullable=False)
    descrizione = Column(Text)


class AssGaranzia(Base):
    __tablename__ = "ass_garanzie"
    __table_args__ = {'schema': 'public'}

    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String(150), nullable=False, unique=True)
    descrizione = Column(Text)


class AssProdottoGaranzia(Base):
    __tablename__ = "ass_prodotti_garanzie"
    __table_args__ = {'schema': 'public'}

    id = Column(Integer, primary_key=True, index=True)
    prodotto_id = Column(Integer, ForeignKey("public.ass_prodotti.id"), nullable=False)
    garanzia_id = Column(Integer, ForeignKey("public.ass_garanzie.id"), nullable=False)


class AssMassimaliFranchigie(Base):
    __tablename__ = "ass_massimali_franchigie"
    __table_args__ = {'schema': 'public'}

    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String(150), nullable=False)
    valore = Column(Numeric(12, 2), nullable=False)


class AssGaranzieMF(Base):
    __tablename__ = "ass_garanzie_mf"
    __table_args__ = {'schema': 'public'}

    id = Column(Integer, primary_key=True, index=True)
    garanzia_id = Column(Integer, ForeignKey("public.ass_garanzie.id"), nullable=False)
    mf_id = Column(Integer, ForeignKey("public.ass_massimali_franchigie.id"), nullable=False)


class AssPreventivo(Base):
    __tablename__ = "ass_preventivi"
    __table_args__ = {'schema': 'public'}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    id_cliente = Column(Integer, ForeignKey("public.clienti.id"), nullable=False)
    id_prodotto = Column(UUID(as_uuid=True), ForeignKey("public.ass_prodotti.id"), nullable=False)
    id_agenzia = Column(UUID(as_uuid=True), ForeignKey("public.ass_agenzie.id"), nullable=False)
    id_compagnia = Column(UUID(as_uuid=True), ForeignKey("public.ass_compagnie.id"), nullable=False)
    id_ramo = Column(UUID(as_uuid=True), ForeignKey("public.ass_ramo.id"), nullable=False)
    id_frazionamento = Column(UUID(as_uuid=True), ForeignKey("public.ass_frazionamento.id"), nullable=False)
    premio_rata = Column(Numeric(12, 2), nullable=False)
    premio_competenza = Column(Numeric(12, 2), nullable=False)
    id_admin = Column(Integer, nullable=True)
    id_team = Column(Integer, nullable=True)
    data_creazione = Column(DateTime, default=func.now())
    modalita_pagamento_cliente = Column(UUID(as_uuid=True), nullable=True)
    confermato_da_cliente = Column(Boolean, default=False)
    data_scadenza_validita = Column(Date, nullable=True)
    data_accettazione_cliente = Column(DateTime, nullable=True)
    blob_url = Column(String, nullable=True)
    stato = Column(String, nullable=True)

class AssPreventivoGaranzia(Base):
    __tablename__ = "ass_preventivi_garanzie"
    __table_args__ = {'schema': 'public'}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    preventivo_id = Column(UUID(as_uuid=True), ForeignKey("public.ass_preventivi.id"), nullable=False)
    garanzia_id = Column(Integer, ForeignKey("public.ass_garanzie.id"), nullable=False)


class AssPreventivoGaranziaMF(Base):
    __tablename__ = "ass_preventivi_garanzie_mf"
    __table_args__ = {'schema': 'public'}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    prev_garanzia_id = Column(UUID(as_uuid=True), ForeignKey("public.ass_preventivi_garanzie.id"), nullable=False)
    mf_id = Column(Integer, ForeignKey("public.ass_massimali_franchigie.id"), nullable=False)


class AssPreventivoRischio(Base):
    __tablename__ = "ass_preventivi_rischi"
    __table_args__ = {'schema': 'public'}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    preventivo_id = Column(UUID(as_uuid=True), ForeignKey("public.ass_preventivi.id"), nullable=False)
    descrizione = Column(Text)


class AssPreventivoConferma(Base):
    __tablename__ = "ass_preventivi_conferme"
    __table_args__ = {'schema': 'public'}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    preventivo_id = Column(UUID(as_uuid=True), ForeignKey("public.ass_preventivi.id"), nullable=False)
    ip_cliente = Column(String(50))
    data_operazione = Column(DateTime, default=func.now())
    confermato = Column(Boolean, default=False)
    note = Column(Text)


class AssPolizza(Base):
    __tablename__ = "ass_polizze"
    __table_args__ = {'schema': 'public'}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    preventivo_id = Column(UUID(as_uuid=True), ForeignKey("public.ass_preventivi.id"), nullable=False)
    numero_polizza = Column(String(50), nullable=False, unique=True)
    data_decorrenza = Column(Date, nullable=False)
    data_emissione = Column(DateTime, default=func.now())


class AssIncasso(Base):
    __tablename__ = "ass_incassi"
    __table_args__ = {'schema': 'public'}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    polizza_id = Column(UUID(as_uuid=True), ForeignKey("public.ass_polizze.id"), nullable=False)
    importo = Column(Numeric(12, 2), nullable=False)
    data_incasso = Column(DateTime, default=func.now())
    metodo_pagamento = Column(String(100), nullable=True)
