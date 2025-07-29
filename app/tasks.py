from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, timedelta
from app.database import SessionLocal
from app.models import User, PurchasedServices, Services
from sqlalchemy import text
import logging
from app.utils.modelli import pulizia_massiva_modelli
from app.routes.sync_dettagli_nuovo import sync_dettagli_auto
from app.routes.sync_marche_completo import sync_marche
from app.routes.sync_modelli_nuovo import sync_modelli
from app.routes.sync_allestimenti_nuovo import sync_allestimenti
from app.routes.invia_reminder_pipeline import invia_reminder_pipeline
from app.utils.aggiorna_usato_settimanale import aggiorna_usato_settimanale



# Configurazione dei log
logging.basicConfig(filename="cron_job.log", level=logging.DEBUG, format="%(asctime)s - %(levelname)s - %(message)s")

def check_and_charge_services():
    logging.info("🚀 CRON JOB ESEGUITO (APScheduler)")
    db = SessionLocal()

    setting = db.execute(text("SELECT service_duration_minutes FROM settings")).fetchone()
    default_duration = setting.service_duration_minutes if setting else 43200  # 30 giorni

    purchased_services = db.query(PurchasedServices).all()

    for purchased in purchased_services:
        service = db.query(Services).filter(Services.id == purchased.service_id).first()
        admin = db.query(User).filter(User.id == purchased.admin_id).first()

        if not service or not admin:
            continue

        expiration_time = purchased.activated_at + timedelta(minutes=default_duration)

        if datetime.utcnow() >= expiration_time:
            if admin.credit >= service.price:
                admin.credit -= service.price
                purchased.activated_at = datetime.utcnow()
                db.execute(
                    text("INSERT INTO logs (admin_email, event_type, message) VALUES (:email, :event, :msg)"),
                    {"email": admin.email, "event": "rinnovo", "msg": f"Servizio {service.name} rinnovato"}
                )
                db.commit()
                logging.info(f"✅ Servizio {service.name} rinnovato per {admin.email}")
            else:
                purchased.status = "sospeso"
                db.execute(
                    text("INSERT INTO logs (admin_email, event_type, message) VALUES (:email, :event, :msg)"),
                    {"email": admin.email, "event": "sospensione", "msg": f"Servizio {service.name} sospeso"}
                )
                db.commit()
                logging.warning(f"⚠️ Servizio {service.name} sospeso per credito insufficiente ({admin.email})")

        # 🔁 Controllo scadenza opzioni auto usate
    durata_opzione = timedelta(hours=168)  # ⏳ durata opzione in ore

    auto_opzionate = db.execute(text("""
        SELECT id, opzionato_da, opzionato_il FROM azlease_usatoin
        WHERE opzionato_da IS NOT NULL AND opzionato_il IS NOT NULL AND visibile = true
    """)).fetchall()

    for auto in auto_opzionate:
        scadenza = auto.opzionato_il + durata_opzione

        if datetime.utcnow() >= scadenza:
            db.execute(text("""
                UPDATE azlease_usatoin
                SET opzionato_da = NULL, opzionato_il = NULL
                WHERE id = :id
            """), {"id": auto.id})

            db.execute(text("""
                INSERT INTO logs (admin_email, event_type, message)
                VALUES (:email, :event, :msg)
            """), {
                "email": "sistema",  # o eventualmente un lookup su opzionato_da
                "event": "scadenza_opzione",
                "msg": f"Opzione scaduta automaticamente per auto ID {auto.id}"
            })

            db.commit()
            logging.info(f"⏳ Opzione scaduta per auto ID {auto.id}")


    db.close()

def pulisci_modelli_settimanale():
    logging.info("🧹 Avvio pulizia settimanale modelli...")
    db = SessionLocal()
    try:
        pulizia_massiva_modelli(db)
        logging.info("✅ Pulizia modelli completata.")
    except Exception as e:
        logging.error(f"❌ Errore nella pulizia modelli: {e}")
    finally:
        db.close()

def sync_dettagli_settimanale():
    print("🛠️ Avvio job settimanale: sync dettagli auto")
    try:
        sync_dettagli_auto()
        print("✅ Sync dettagli completato.")
    except Exception as e:
        print(f"❌ Errore durante sync dettagli: {e}")

def sync_allestimenti_settimanale():
    logging.info("🧩 Avvio sync allestimenti settimanale...")
    try:
        sync_allestimenti()
        logging.info("✅ Sync allestimenti completato.")
    except Exception as e:
        logging.error(f"❌ Errore nella sync allestimenti: {e}")

def sync_marche_settimanale():
    logging.info("🚗 Avvio sync marche settimanale...")
    try:
        sync_marche()
        logging.info("✅ Sync marche completato.")
    except Exception as e:
        logging.error(f"❌ Errore nella sync marche: {e}")


def sync_modelli_settimanale():
    logging.info("📦 Avvio sync modelli settimanale...")
    try:
        sync_modelli()
        logging.info("✅ Sync modelli completato.")
    except Exception as e:
        logging.error(f"❌ Errore nella sync modelli: {e}")


from app.utils.quotazioni import aggiorna_rating_convenienza

def aggiorna_rating_convenienza_job():
    logging.info("📊 Avvio aggiornamento rating convenienza...")
    db = SessionLocal()
    try:
        aggiorna_rating_convenienza(db)
        logging.info("✅ Rating convenienza aggiornato con successo.")
    except Exception as e:
        logging.error(f"❌ Errore durante aggiornamento rating convenienza: {e}")
    finally:
        db.close()




scheduler = BackgroundScheduler(job_defaults={'coalesce': True, 'max_instances': 1})

scheduler.add_job(check_and_charge_services, 'interval', minutes=500)
# Ogni lunedì alle 03:00
scheduler.add_job(pulisci_modelli_settimanale, 'cron', day_of_week='mon', hour=3, minute=0)
# Ogni lunedì alle 04:00
scheduler.add_job(sync_dettagli_settimanale, 'cron', day_of_week='mon', hour=4, minute=0)
# Ogni lunedì alle 02:30
scheduler.add_job(sync_allestimenti_settimanale, 'cron', day_of_week='mon', hour=2, minute=30)
# Ogni lunedì alle 01:00
scheduler.add_job(sync_marche_settimanale, 'cron', day_of_week='mon', hour=1, minute=0)

# Ogni lunedì alle 02:00
scheduler.add_job(sync_modelli_settimanale, 'cron', day_of_week='mon', hour=2, minute=0)

# Invia reminder pipeline ogni giorno lavorativo dalle 9:00 alle 17:30 ogni 30 minuti
#scheduler.add_job(invia_reminder_pipeline, 'cron', day_of_week='mon-fri', hour='9-17', minute='*/30')

# TEST: invia ogni 3 minuti, tutti i giorni
scheduler.add_job(invia_reminder_pipeline, 'interval', minutes=30)

# Ogni notte alle 3:30
scheduler.add_job(aggiorna_rating_convenienza_job, 'cron', hour=3, minute=30)

# Ogni martedì alle 01:00 → sync completo usato, solo se ci sono modelli
scheduler.add_job(aggiorna_usato_settimanale, 'cron', day_of_week='tue', hour=1, minute=0)

