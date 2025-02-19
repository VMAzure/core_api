import schedule
import time
from datetime import datetime, timedelta
from app.database import SessionLocal
from app.models import User, PurchasedServices, Services

def check_and_charge_services():
    db = SessionLocal()

    # Recupera la durata globale impostata dal Super Admin
    setting = db.execute("SELECT service_duration_minutes FROM settings").fetchone()
    default_duration = setting.service_duration_minutes if setting else 43200  # Default: 30 giorni

    # Trova tutti i servizi acquistati dagli Admin
    purchased_services = db.query(PurchasedServices).all()

    for purchased in purchased_services:
        service = db.query(Services).filter(Services.id == purchased.service_id).first()
        admin = db.query(User).filter(User.id == purchased.admin_id).first()

        if not service or not admin:
            continue  # Se l'Admin o il servizio non esistono più, passa oltre

        # Usa la durata del servizio o la durata globale
        service_duration = service.duration_minutes or default_duration
        expiration_time = purchased.activated_at + timedelta(minutes=service_duration)

        if datetime.utcnow() >= expiration_time:
            if admin.credit >= service.price:
                # Scala il credito e rinnova il servizio
                admin.credit -= service.price
                purchased.activated_at = datetime.utcnow()  # Reset scadenza
                db.commit()
                print(f"✅ Servizio {service.name} rinnovato per {admin.email}")
            else:
                # Credito insufficiente: sospende il servizio
                purchased.status = "sospeso"
                db.commit()
                print(f"❌ Credito insufficiente per {admin.email}, servizio {service.name} sospeso!")

    db.close()

# Controlla ogni minuto
schedule.every(1).minutes.do(check_and_charge_services)

def run_scheduler():
    while True:
        schedule.run_pending()
        time.sleep(60)  # Controlla ogni minuto
