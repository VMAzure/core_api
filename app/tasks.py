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
import asyncio

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


from app.routes.openai_config import _gemini_get_operation, _download_bytes, _sb_upload_and_sign
from app.models import UsatoLeonardo
import logging
from pprint import pprint  # se preferisci invece di json.dumps

async def polla_video_gemini():
    logging.info("🎥 Polling Gemini video VEO3...")
    db = SessionLocal()
    try:
        recs = db.query(UsatoLeonardo).filter(
            UsatoLeonardo.media_type == "video",
            UsatoLeonardo.status == "processing",
            UsatoLeonardo.generation_id.isnot(None)
        ).all()

        for rec in recs:
            try:
                op = await _gemini_get_operation(rec.generation_id)
                if not op.get("done", False):
                    continue  # ancora in elaborazione

                # Estrai URI compatibile con struttura Gemini VEO 3
                resp = op.get("response", {})
                vid0 = (resp.get("generatedVideos") or [{}])[0]
                video_obj = vid0.get("video") or {}
                uri = (
                    vid0.get("uri")
                    or video_obj.get("uri")
                    or video_obj.get("videoUri")
                )


                if not uri:
                    rec.status = "failed"
                    rec.error_message = "URI video mancante dal response Gemini"
                    db.commit()
                    continue

                # Scarica e salva su Supabase
                blob = await _download_bytes(uri)
                ext = ".mp4"
                path = f"{str(rec.id_auto)}/{str(rec.id)}{ext}"
                _, public_url = _sb_upload_and_sign(path, blob, "video/mp4")

                # Attiva solo se nessun altro attivo
                other_active = db.query(UsatoLeonardo).filter(
                    UsatoLeonardo.id_auto == rec.id_auto,
                    UsatoLeonardo.media_type == "video",
                    UsatoLeonardo.is_active == True,
                    UsatoLeonardo.id != rec.id
                ).count()

                rec.status = "completed"
                rec.public_url = public_url
                rec.storage_path = path
                rec.is_active = other_active == 0

                db.commit()
                logging.info(f"✅ Video Gemini completato: {rec.id}")
                op = await _gemini_get_operation(rec.generation_id)
                pprint(op) 

            except Exception as e:
                db.rollback()
                rec.status = "failed"
                rec.error_message = str(e)
                db.commit()
                logging.warning(f"❌ Errore polling video {rec.id}: {e}")

    except Exception as e:
        logging.error(f"❌ Errore cronjob polla_video_gemini: {e}")
        db.rollback()
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

# Video Gemin veo
from apscheduler.triggers.interval import IntervalTrigger
from app.routes.openai_config import _gemini_get_operation, _download_bytes, _sb_upload_and_sign
from app.models import UsatoLeonardo
from apscheduler.schedulers.asyncio import AsyncIOScheduler

scheduler = AsyncIOScheduler(job_defaults={'coalesce': True, 'max_instances': 1})
scheduler.add_job(polla_video_gemini, IntervalTrigger(seconds=60))

