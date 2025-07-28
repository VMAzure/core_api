from dotenv import load_dotenv
load_dotenv(dotenv_path=".env")  # Assicura il caricamento delle variabili

from app.tasks import aggiorna_rating_convenienza_job

if __name__ == "__main__":
    print("🚀 Avvio aggiornamento rating convenienza...")
    aggiorna_rating_convenienza_job()
    print("✅ Completato!")
