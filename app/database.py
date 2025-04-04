import os
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()



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

# Configurazione Supabase Client
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Importiamo i modelli per assicurarci che siano registrati prima della creazione delle tabelle
from app import models

 
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
