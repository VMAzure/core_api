import schedule
import time
from datetime import datetime, timedelta
from app.database import SessionLocal
from app.models import User, PurchasedServices, Services
import logging
from sqlalchemy import text

# Configura i log
logging.basicConfig(filename="cron_job.log", level=logging.DEBUG, format="%(asctime)s - %(levelname)s - %(message)s")

def check_and_charge_services():
    db = SessionLocal()
    
    # Recupera la durata impostata dal Super Admin
    setting = db.execute(text("SELECT service_duration_minutes FROM settings")).fetchone()
    default_duration = setting.service_duration_minutes if setting else 43200  # Default: 30 giorni

    logging.info("🔍 Controllo servizi scaduti avviato...")

    purchased_services = db.query(PurchasedServices).all()

    for purchased in purchased_services:
        service = db.query(Services).filter(Services.id == purchased.service_id).first()
        admin = db.query(User).filter(User.id == purchased.admin_id).first()

        if not service or not admin:
            continue

        service_duration = service.duration_minutes or default_duration
        expiration_time = purchased.activated_at + timedelta(minutes=service_duration)

        logging.info(f"⏳ Controllando servizio {service.id} per {admin.email} - Scade alle {expiration_time}")

        if datetime.utcnow() >= expiration_time:
            if admin.credit >= service.price:
                admin.credit -= service.price
                purchased.activated_at = datetime.utcnow()  # Reset scadenza
                db.commit()
                logging.info(f"✅ Servizio {service.name} rinnovato per {admin.email}, nuovo credito: {admin.credit}")
            else:
                purchased.status = "sospeso"
                db.commit()
                logging.warning(f"❌ Credito insufficiente per {admin.email}, servizio {service.name} sospeso!")

    db.close()
    logging.info("✅ Controllo servizi scaduti completato.")

# Controlla ogni minuto
schedule.every(1).minutes.do(check_and_charge_services)

def run_scheduler():
    while True:
        schedule.run_pending()
        time.sleep(60)  # Controlla ogni minuto
