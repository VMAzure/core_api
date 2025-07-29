import logging
from sqlalchemy import text
from app.database import SessionLocal

def aggiorna_usato_settimanale():
    logging.info("🛠️ Avvio job settimanale aggiornamento usato...")

    db = SessionLocal()
    try:
        # 1. Controllo se ci sono modelli usati
        result = db.execute(text("""
            SELECT COUNT(*) FROM mnet_modelli_usato
        """)).scalar()

        if result == 0:
            logging.info("⏹️ Nessun modello usato presente: skip aggiornamento usato.")
            return

        logging.info(f"📦 Trovati {result} modelli usati → avvio sync completo...")

        # 2. Import dinamici delle sync (evita problemi di import ciclici)
        from app.routes.sync_marche_usato import sync_marche_usato
        from app.routes.sync_modelli_usato import sync_modelli_usato
        from app.routes.sync_allestimenti_usato import sync_allestimenti_usato
        from app.routes.sync_dettagli_usato import sync_dettagli_usato

        # 3. Esecuzione sync usato
        sync_marche_usato()
        logging.info("✅ Sync marche usato completato.")

        sync_modelli_usato()
        logging.info("✅ Sync modelli usato completato.")

        sync_allestimenti_usato()
        logging.info("✅ Sync allestimenti usato completato.")

        sync_dettagli_usato()
        logging.info("✅ Sync dettagli usato completato.")

    except Exception as e:
        logging.error(f"❌ Errore nel job aggiornamento usato: {e}")
    finally:
        db.close()
