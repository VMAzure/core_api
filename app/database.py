import os
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from dotenv import load_dotenv

# Percorso assoluto del file config.env
ENV_PATH = "/home/AzureAutomotive/core_api/config.env"

# Carica le variabili d'ambiente
if os.path.exists(ENV_PATH):
    load_dotenv(ENV_PATH)
else:
    print(f"⚠️ Attenzione: il file {ENV_PATH} non esiste!")

# Otteniamo DATABASE_URL dal file .env
DATABASE_URL = os.getenv("DATABASE_URL")

# Se DATABASE_URL è ancora None, solleviamo un errore per evitare crash silenziosi
if not DATABASE_URL:
    raise ValueError("❌ ERRORE: `DATABASE_URL` non è stato caricato correttamente! Verifica il file config.env.")

# Creiamo l'engine del database
engine = create_engine(DATABASE_URL, echo=True)

# Definiamo Base separatamente
Base = declarative_base()

# Creiamo una session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Importiamo i modelli per assicurarci che siano registrati prima della creazione delle tabelle
from app import models
