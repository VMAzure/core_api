from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, timedelta
from app.database import SessionLocal
from app.models import User, PurchasedServices, Services
from sqlalchemy import text
import logging

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

# Creazione scheduler (NON avviarlo qui, lo avviamo in main.py)
scheduler = BackgroundScheduler()
scheduler.add_job(check_and_charge_services, 'interval', minutes=1)