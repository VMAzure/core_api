from sqlalchemy import Column, Integer, String, Text, Float, DateTime, ForeignKey, func, Boolean, Numeric, Date, TIMESTAMP
from sqlalchemy.orm import relationship
from datetime import datetime, date
from passlib.context import CryptContext
from app.database import Base  # Manteniamo solo Base senza importare engine
from typing import TYPE_CHECKING, Optional, List
from pydantic import BaseModel, EmailStr, Field
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
    open_in_new_tab = Column(Boolean, default=True)
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
    shared_customers = Column(Boolean, default=False, nullable=False)


    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    parent = relationship("User", remote_side=[id], backref="dealers", primaryjoin="User.parent_id == User.id")
    smtp_settings = relationship("SmtpSettings", uselist=False, back_populates="admin", cascade="all, delete-orphan")


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
    preventivo_assegnato_a = Column(Integer, nullable=True)
    note = Column(String, nullable=True)
    player = Column(String, nullable=True)
    cliente = relationship("Cliente")
    creatore = relationship("User", foreign_keys=[creato_da])

class SmtpSettings(Base):
    __tablename__ = "smtp_settings"
    __table_args__ = {"schema": "public"}

    id = Column(Integer, primary_key=True, index=True)
    admin_id = Column(Integer, ForeignKey('public.utenti.id', ondelete='CASCADE'), nullable=False)
    smtp_host = Column(String(255), nullable=False)
    smtp_port = Column(Integer, nullable=False)
    smtp_user = Column(String(255), nullable=False)
    smtp_password = Column(String(255), nullable=False)
    use_ssl = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    admin = relationship("User", back_populates="smtp_settings")

class SiteAdminSettings(Base):
    __tablename__ = "site_admin_settings"
    __table_args__ = {"schema": "public"}

    id = Column(Integer, primary_key=True, index=True)
    admin_id = Column(Integer, ForeignKey("public.utenti.id", ondelete="CASCADE"), nullable=False)
    primary_color = Column(String(7))
    secondary_color = Column(String(7))
    tertiary_color = Column(String(7))
    font_family = Column(String(255))
    favicon_url = Column(String(255))
    custom_css = Column(Text)
    custom_js = Column(Text)
    dark_mode_enabled = Column(Boolean, default=False)
    menu_style = Column(String(50))
    footer_text = Column(Text)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    admin = relationship("User", backref="site_settings")


class SitePages(Base):
    __tablename__ = "site_pages"
    __table_args__ = {"schema": "public"}

    id = Column(Integer, primary_key=True, index=True)
    admin_id = Column(Integer, ForeignKey("public.utenti.id", ondelete="CASCADE"), nullable=False)
    page_name = Column(String(100))
    page_url = Column(String(255), unique=True)
    is_active = Column(Boolean, default=True)
    sort_order = Column(Integer, default=0)
    parent_page_id = Column(Integer, ForeignKey("public.site_pages.id", ondelete="SET NULL"), nullable=True)
    seo_title = Column(String(150))
    seo_description = Column(String(160))
    seo_keywords = Column(String(255))
    meta_robots = Column(String(50), default="index, follow")
    canonical_url = Column(String(255))
    json_ld_schema = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    parent_page = relationship("SitePages", remote_side=[id], backref="sub_pages")

class Danno(BaseModel):
    foto: str
    valore_perizia: float
    descrizione: str
 

class AZUsatoInsertRequest(BaseModel):
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
    immagini: Optional[List[str]] = []
    danni: Optional[List[Danno]] = []
    opzionato_da: Optional[str] = None
    opzionato_il: Optional[str] = None
    venduto_da: Optional[str] = None
    venduto_il: Optional[str] = None
    visibile: Optional[bool] = True

class NltOfferte(Base):
    __tablename__ = 'nlt_offerte'

    id_offerta = Column(Integer, primary_key=True)
    id_admin = Column(Integer, nullable=False)
    marca = Column(String(100), nullable=False)
    modello = Column(String(100), nullable=False)
    versione = Column(String(100), nullable=False)
    codice_motornet = Column(String(50), nullable=False)
    id_player = Column(Integer, ForeignKey('nlt_players.id_player'), nullable=False)
    data_inserimento = Column(DateTime, default=datetime.utcnow)
    attivo = Column(Boolean, default=True)
    descrizione_breve = Column(String(255), nullable=True)
    valido_da = Column(Date, nullable=True)
    valido_fino = Column(Date, nullable=True)

    player = relationship("NltPlayers", back_populates="offerte")
    quotazioni = relationship("NltQuotazioni", back_populates="offerta", cascade="all, delete-orphan")
    immagini = relationship("NltImmagini", back_populates="offerta", cascade="all, delete-orphan")
    tags = relationship("NltOfferteTag", secondary="nlt_offerta_tag", back_populates="offerte")
    prezzo_accessori = Column(Numeric(10, 2))
    prezzo_mss = Column(Numeric(10, 2))
    prezzo_listino = Column(Numeric(10, 2))
    prezzo_totale = Column(Numeric(10, 2))

class NltQuotazioni(Base):
    __tablename__ = 'nlt_quotazioni'

    id_quotazione = Column(Integer, primary_key=True)
    id_offerta = Column(Integer, ForeignKey('nlt_offerte.id_offerta', ondelete='CASCADE'))
    mesi_36_10 = Column("36_10", Numeric(10, 2))
    mesi_36_15 = Column("36_15", Numeric(10, 2))
    mesi_36_20 = Column("36_20", Numeric(10, 2))
    mesi_36_25 = Column("36_25", Numeric(10, 2))
    mesi_36_30 = Column("36_30", Numeric(10, 2))
    mesi_36_40 = Column("36_40", Numeric(10, 2))
    mesi_48_10 = Column("48_10", Numeric(10, 2))
    mesi_48_15 = Column("48_15", Numeric(10, 2))
    mesi_48_20 = Column("48_20", Numeric(10, 2))
    mesi_48_25 = Column("48_25", Numeric(10, 2))
    mesi_48_30 = Column("48_30", Numeric(10, 2))
    mesi_48_40 = Column("48_40", Numeric(10, 2))

    offerta = relationship("NltOfferte", back_populates="quotazioni")

class NltImmagini(Base):
    __tablename__ = 'nlt_immagini'

    id_immagine = Column(Integer, primary_key=True)
    id_offerta = Column(Integer, ForeignKey('nlt_offerte.id_offerta', ondelete='CASCADE'))
    url_imagin = Column(String(255), nullable=False)
    principale = Column(Boolean, default=False)

    offerta = relationship("NltOfferte", back_populates="immagini")

class NltOfferteTag(Base):
    __tablename__ = 'nlt_offerte_tag'

    id_tag = Column(Integer, primary_key=True)
    nome = Column(String(50), nullable=False, unique=True)
    fa_icon = Column(String(50), nullable=False)
    colore = Column(String(7), nullable=False)

    offerte = relationship("NltOfferte", secondary="nlt_offerta_tag", back_populates="tags")

class NltOffertaTag(Base):
    __tablename__ = 'nlt_offerta_tag'

    id_offerta = Column(Integer, ForeignKey('nlt_offerte.id_offerta', ondelete='CASCADE'), primary_key=True)
    id_tag = Column(Integer, ForeignKey('nlt_offerte_tag.id_tag', ondelete='CASCADE'), primary_key=True)

class NltPlayers(Base):
    __tablename__ = 'nlt_players'

    id_player = Column(Integer, primary_key=True)
    nome = Column(String(100), nullable=False, unique=True)
    colore = Column(String(7), nullable=False)

    offerte = relationship("NltOfferte", back_populates="player")

class NltOffertaAccessori(Base):
    __tablename__ = 'nlt_offerta_accessori'

    id = Column(Integer, primary_key=True)
    id_offerta = Column(Integer, ForeignKey('nlt_offerte.id_offerta', ondelete='CASCADE'))
    codice = Column(String(20), nullable=False)
    descrizione = Column(Text, nullable=False)
    prezzo = Column(Numeric(10, 2), nullable=False)

    # relazione inversa opzionale, se vuoi accedere da NltOfferte agli accessori
    offerta = relationship("NltOfferte", backref="accessori")

class MotornetImaginAlias(Base):
    __tablename__ = "motornet_imagin_alias"

    make = Column(String, primary_key=True)
    model_family = Column(String, primary_key=True)
    model_range = Column(String, primary_key=True)
    model_variant = Column(String, primary_key=True)

    alias_make = Column(String, nullable=True)
    alias_model_family = Column(String, nullable=True)
    alias_model_range = Column(String, nullable=True)
    alias_model_variant = Column(String, nullable=True)

class MnetModelli(Base):
    __tablename__ = "mnet_modelli"

    codice_modello = Column(String, primary_key=True, index=True)
    descrizione = Column(String, nullable=False)
    marca_acronimo = Column(String, nullable=False, index=True)
    inizio_produzione = Column(Date, nullable=True)
    fine_produzione = Column(Date, nullable=True)
    gruppo_storico_codice = Column(String, nullable=True)
    gruppo_storico_descrizione = Column(String, nullable=True)
    serie_gamma_codice = Column(String, nullable=True)
    serie_gamma_descrizione = Column(String, nullable=True)
    cod_desc_modello_codice = Column(String, nullable=True)
    cod_desc_modello_descrizione = Column(String, nullable=True)
    inizio_commercializzazione = Column(Date, nullable=True)
    fine_commercializzazione = Column(Date, nullable=True)
    modello = Column(String, nullable=True)
    foto = Column(String, nullable=True)
    prezzo_minimo = Column(String, nullable=True)
    modello_breve_carrozzeria = Column(String, nullable=True)
    ultima_modifica = Column(DateTime, server_default=func.now(), onupdate=func.now())

class MnetAllestimenti(Base):
    __tablename__ = "mnet_allestimenti"

    id = Column(Integer, primary_key=True, autoincrement=True)
    codice_modello = Column(String, ForeignKey("mnet_modelli.codice_modello", ondelete="CASCADE"), nullable=False)
    codice_motornet_uni = Column(String, unique=True, nullable=False)
    nome = Column(String, nullable=False)
    data_da = Column(Date)
    data_a = Column(Date)
    ultima_modifica = Column(DateTime, default=func.now(), onupdate=func.now())

class MnetMarche(Base):
    __tablename__ = "mnet_marche"

    acronimo = Column(String, primary_key=True, index=True)
    nome = Column(String, nullable=False)
    logo = Column(Text, nullable=False)
    utile = Column(Boolean, default=True)  # ✅ nuova colonna


class MnetDettagli(Base):
    __tablename__ = "mnet_dettagli"

    codice_motornet_uni = Column(String, primary_key=True)

    alimentazione = Column(Text)
    cilindrata = Column(Integer)
    hp = Column(Integer)
    kw = Column(Integer)
    euro = Column(Text)

    consumo_medio = Column(Float)
    consumo_urbano = Column(Float)
    consumo_extraurbano = Column(Float)
    emissioni_co2 = Column(Text)

    tipo_cambio = Column(Text)
    trazione = Column(Text)
    porte = Column(Integer)
    posti = Column(Integer)
    lunghezza = Column(Integer)
    larghezza = Column(Integer)
    altezza = Column(Integer)
    altezza_minima = Column(Integer)

    peso = Column(Integer)
    peso_vuoto = Column(Text)
    peso_potenza = Column(Text)
    portata = Column(Integer)

    velocita = Column(Integer)
    accelerazione = Column(Float)

    bagagliaio = Column(Text)
    descrizione_breve = Column(Text)
    foto = Column(Text)
    prezzo_listino = Column(Float)
    prezzo_accessori = Column(Float)
    data_listino = Column(Date)

    neo_patentati = Column(Boolean)
    architettura = Column(Text)
    coppia = Column(Text)
    coppia_ibrido = Column(Text)
    coppia_totale = Column(Text)

    numero_giri = Column(Integer)
    numero_giri_ibrido = Column(Integer)
    numero_giri_totale = Column(Integer)

    valvole = Column(Integer)
    passo = Column(Integer)

    cilindri = Column(Text)
    cavalli_fiscali = Column(Integer)

    pneumatici_anteriori = Column(Text)
    pneumatici_posteriori = Column(Text)

    massa_p_carico = Column(Text)
    indice_carico = Column(Text)
    codice_velocita = Column(Text)

    cap_serb_litri = Column(Integer)
    cap_serb_kg = Column(Float)

    paese_prod = Column(Text)
    tipo_guida = Column(Text)
    tipo_motore = Column(Text)
    descrizione_motore = Column(Text)

    cambio_descrizione = Column(Text)
    nome_cambio = Column(Text)
    marce = Column(Text)

    codice_costruttore = Column(String)
    modello_breve_carrozzeria = Column(Text)

    tipo = Column(Text)
    tipo_descrizione = Column(Text)
    segmento = Column(Text)
    segmento_descrizione = Column(Text)

    garanzia_km = Column(Integer)
    garanzia_tempo = Column(Integer)
    guado = Column(Integer)
    pendenza_max = Column(Integer)
    sosp_pneum = Column(Boolean)

    tipo_batteria = Column(Text)
    traino = Column(Integer)
    volumi = Column(Text)

    cavalli_ibrido = Column(Integer)
    cavalli_totale = Column(Integer)
    potenza_ibrido = Column(Integer)
    potenza_totale = Column(Integer)

    motore_elettrico = Column(Text)
    motore_ibrido = Column(Text)
    capacita_nominale_batteria = Column(Float)
    capacita_netta_batteria = Column(Float)
    cavalli_elettrico_max = Column(Integer)
    cavalli_elettrico_boost_max = Column(Integer)
    potenza_elettrico_max = Column(Integer)
    potenza_elettrico_boost_max = Column(Integer)

    autonomia_media = Column(Float)
    autonomia_massima = Column(Float)

    equipaggiamento = Column(Text)
    hc = Column(Text)
    nox = Column(Text)
    pm10 = Column(Text)
    tipo_cons = Column(Text)
    wltp = Column(Text)

    ridotte = Column(Boolean)

    freni = Column(Text)

    ultima_modifica = Column(TIMESTAMP, default=func.now(), onupdate=func.now())









