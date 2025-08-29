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

from app.utils.notifications import inserisci_notifica
from app.utils.email import get_smtp_settings
from sqlalchemy.orm import joinedload
import smtplib
from email.mime.text import MIMEText
from email.utils import formataddr

from app.utils.video_jobs import (
    video_daily_batch,
    video_revalidate_existing,
    video_weekly_sweep,
)



# Configurazione dei log
logging.basicConfig(filename="cron_job.log", level=logging.DEBUG, format="%(asctime)s - %(levelname)s - %(message)s")

def calcola_prossima_scadenza(current: datetime, cycle: str) -> datetime:
    return {
        "monthly": current + timedelta(days=30),
        "quarterly": current + timedelta(days=90),
        "semiannual": current + timedelta(days=182),
        "annual": current + timedelta(days=365)
    }.get(cycle, current + timedelta(days=30))

def check_and_charge_services():
    logging.info("🚀 CRONJOB: check_and_charge_services avviato")
    db = SessionLocal()
    now = datetime.utcnow()

    soglie_avviso = {
        "monthly": [10, 2],
        "quarterly": [10, 2],
        "semiannual": [30, 5],
        "annual": [30, 5]
    }

    try:
        servizi_attivi = db.query(PurchasedServices).join(Services).options(
            joinedload(PurchasedServices.service),
            joinedload(PurchasedServices.dealer)
        ).filter(
            PurchasedServices.status == "attivo",
            PurchasedServices.billing_cycle.isnot(None),
            PurchasedServices.next_renewal_at.isnot(None),
            PurchasedServices.dealer_id.isnot(None),
            Services.is_pay_per_use == False   # ⬅️ ESCLUDE i pay-per-use
        ).all()

        for ps in servizi_attivi:
            service = ps.service
            dealer = ps.dealer
            billing_cycle = ps.billing_cycle
            giorni_mancanti = (ps.next_renewal_at.date() - now.date()).days

            # 🔔 Avvisi pre-scadenza
            if giorni_mancanti in soglie_avviso.get(billing_cycle, []):
                admin_id = dealer.parent_id
                smtp = get_smtp_settings(admin_id, db)

                if smtp:
                    html = f"<p>Il tuo servizio <strong>{service.name}</strong> scadrà tra {giorni_mancanti} giorni.</p><p>Controlla il credito disponibile per evitare la sospensione automatica.</p>"
                    msg = MIMEText(html, "html", "utf-8")
                    msg["Subject"] = f"🔔 Servizio '{service.name}' in scadenza"
                    msg["From"] = formataddr((smtp.smtp_alias or "AZ Core", smtp.smtp_user))
                    msg["To"] = dealer.email

                    try:
                        server = smtplib.SMTP_SSL(smtp.smtp_host, smtp.smtp_port) if smtp.use_ssl else smtplib.SMTP(smtp.smtp_host, smtp.smtp_port)
                        if not smtp.use_ssl:
                            server.starttls()
                        server.login(smtp.smtp_user, smtp.smtp_password)
                        server.send_message(msg)
                        server.quit()
                        logging.info(f"📧 Avviso inviato a {dealer.email} per {service.name}")
                    except Exception as e:
                        logging.error(f"❌ Errore invio email avviso a {dealer.email}: {e}")

                # 🔔 Scrivi notifica
                inserisci_notifica(
                    db, utente_id=dealer.id,
                    tipo_codice="scadenza_servizio",
                    messaggio=f"Il servizio '{service.name}' scadrà tra {giorni_mancanti} giorni."
                )

            # 🔁 Rinnovo
            if now >= ps.next_renewal_at:
                price = {
                    "monthly": service.monthly_price,
                    "quarterly": service.quarterly_price,
                    "semiannual": service.semiannual_price,
                    "annual": service.annual_price
                }.get(billing_cycle, 0)

                if dealer.credit >= price:
                    dealer.credit -= price
                    ps.activated_at = now
                    ps.next_renewal_at = calcola_prossima_scadenza(now, billing_cycle)
                    db.commit()
                    logging.info(f"✅ Servizio rinnovato: {service.name} per {dealer.email}")
                else:
                    ps.status = "sospeso"
                    db.commit()

                    # ❌ Email sospensione
                    admin_id = dealer.parent_id
                    smtp = get_smtp_settings(admin_id, db)

                    if smtp:
                        html = f"<p>Il servizio <strong>{service.name}</strong> è stato sospeso per credito insufficiente.</p><p>Puoi riattivarlo dallo Store dopo aver ricaricato il credito.</p>"
                        msg = MIMEText(html, "html", "utf-8")
                        msg["Subject"] = f"❌ Servizio '{service.name}' sospeso"
                        msg["From"] = formataddr((smtp.smtp_alias or "AZ Core", smtp.smtp_user))
                        msg["To"] = dealer.email

                        try:
                            server = smtplib.SMTP_SSL(smtp.smtp_host, smtp.smtp_port) if smtp.use_ssl else smtplib.SMTP(smtp.smtp_host, smtp.smtp_port)
                            if not smtp.use_ssl:
                                server.starttls()
                            server.login(smtp.smtp_user, smtp.smtp_password)
                            server.send_message(msg)
                            server.quit()
                            logging.info(f"📧 Email sospensione a {dealer.email} per {service.name}")
                        except Exception as e:
                            logging.error(f"❌ Errore invio email sospensione a {dealer.email}: {e}")

                    # 🛑 Scrivi notifica sospensione
                    inserisci_notifica(
                        db, utente_id=dealer.id,
                        tipo_codice="sospensione_servizio",
                        messaggio=f"Il servizio '{service.name}' è stato sospeso per credito insufficiente."
                    )

    except Exception as e:
        db.rollback()
        logging.error(f"❌ Errore cronjob servizi: {e}")
    finally:
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

# Ogni mattina alle 05:00
scheduler.add_job(check_and_charge_services, 'cron', hour=5, minute=0)
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

# Invia ogni 30 minuti, tutti i giorni
scheduler.add_job(invia_reminder_pipeline, 'interval', minutes=30)

# Ogni notte alle 3:30
scheduler.add_job(aggiorna_rating_convenienza_job, 'cron', hour=3, minute=30)

# Ogni martedì alle 01:00 → sync completo usato, solo se ci sono modelli
scheduler.add_job(aggiorna_usato_settimanale, 'cron', day_of_week='tue', hour=1, minute=0)

# Video jobs
scheduler.add_job(video_revalidate_existing, 'cron', hour=2,  minute=45)   # daily light
scheduler.add_job(video_daily_batch,       'cron', hour=5,  minute=20)   # daily search
scheduler.add_job(video_weekly_sweep,      'cron', day_of_week='sun', hour=5, minute=40)  # weekly


