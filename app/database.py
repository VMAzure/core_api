import os
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from dotenv import load_dotenv

# Determiniamo se siamo in ambiente di produzione o sviluppo
ENV_FILE = "config.env" if os.getenv("RAILWAY_ENVIRONMENT") else "config.dev.env"

# Percorso assoluto del file di configurazione
env_path = os.path.join(os.path.dirname(__file__), "..", ENV_FILE)

# Carichiamo le variabili d'ambiente
if os.path.exists(env_path):
    load_dotenv(env_path)
    print(f"✅ Variabili d'ambiente caricate da {env_path}")
else:
    raise ValueError(f"❌ ERRORE: Il file {env_path} non esiste! Crealo nella cartella principale del progetto.")

# Otteniamo DATABASE_URL dal file di configurazione
DATABASE_URL = os.getenv("DATABASE_URL")

# Se DATABASE_URL è ancora None, solleviamo un errore per evitare crash silenziosi
if not DATABASE_URL:
    raise ValueError("❌ ERRORE: `DATABASE_URL` non è stato caricato correttamente! Verifica il file di configurazione.")

# Creiamo l'engine del database
engine = create_engine(DATABASE_URL, echo=True)

# Definiamo Base separatamente
Base = declarative_base()

# Creiamo una session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Importiamo i modelli per assicurarci che siano registrati prima della creazione delle tabelle
from app import models

